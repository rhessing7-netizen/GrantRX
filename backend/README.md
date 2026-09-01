# GrantRx Backend

FastAPI REST API and ingestion workers for the GrantRx scholarship matching platform, backed by PostgreSQL/Supabase.

## Setup

1. Copy the environment template:
   ```bash
   cp .env.example .env
   ```

2. Fill in `.env` with your Supabase project URL, anon key, and **JWT secret**.

3. Apply the database migration in the Supabase SQL Editor or via `psql`:
   ```bash
   psql $DATABASE_URL -f migrations/001_initial_schema.sql
   ```

4. Install dependencies:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

5. Run the API:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

## Authentication

All endpoints except `/health`, `/docs`, `/redoc`, and `/openapi.json` require a valid Supabase `Authorization: Bearer <access_token>` header.

## Row Level Security

RLS policies in `migrations/001_initial_schema.sql` enforce:
- Users can only access their own `profiles` row.
- Authenticated users can read `scholarships`.
- Users can only manage their own `user_scholarships` rows.
- The `service_role` can manage `scholarships` and run ingestion.

The FastAPI backend also filters by the decoded JWT `sub` claim where applicable.

## Matching Engine & Tier Gating

### Compatibility Score (0-100%)

`app/services/matcher.py` scores each non-archived scholarship against the
user's profile. **Primary discipline is a hard filter** — scholarships whose
`eligible_disciplines` does not contain `profile.primary_discipline` are
excluded before scoring.

| Criterion                                  | Points |
|--------------------------------------------|--------|
| Award credential match                     | +25%   |
| GPA requirement met (`gpa >= min_gpa`)     | +20%   |
| Need/SAI limit met (`sai <= max_sai`)      | +20%   |
| State residence match                      | +15%   |
| Affiliations / identity / tag overlap      | +20%   |

For any scholarship scoring below 100%, an explicit `missing_criteria` array
of human-readable strings is returned (e.g. `["Requires GPA >= 3.8",
"Restricted to residents of: CA"]`).

### Free-Tier Access Control (`app/middleware/tier_guard.py`)

- Free users: **5 searches per 7-day rolling cycle**.
- A 6th attempt returns **HTTP 402** with
  `{"upgrade_required": true, "reason": "search_limit_reached", "reset_at": "..."}`.
- For free users, only the **top 3** highest-scoring results are fully
  visible. Results 4+ return masked titles/providers, `is_locked: true`,
  and no `portal_url`.
- Premium users: unlimited searches, no masking.

### Endpoints

- `GET /api/scholarships/matched` — runs the matching engine, consumes a
  search, and returns the tier-gated feed with `missing_criteria`.
- `GET /api/user/usage` — returns current search count, limit, and
  `reset_at` timestamp.

## Hybrid Scraping Pipeline (`scrapers/`)

A modular pipeline that combines fast deterministic BeautifulSoup parsers with
an LLM fallback extractor (OpenAI `gpt-4o-mini` via `instructor`, or LiteLLM).

### Architecture

1. **Fast-path deterministic parsers** (`scrapers/parsers/deterministic.py`)
   - CSS-selector / label-based rules for structured portals (APhA, AACN,
     state `.gov` higher-ed boards, generic "scholarship" pages).
   - Registered via `@register_parser("host-substring")`; new portals are
     added by decorating a new parser function.
   - Cost: $0 per page.
2. **LLM fallback** (`scrapers/llm_parser.py`)
   - Triggered only when (a) no deterministic parser matches, or (b) a
     deterministic parser ran but a critical field (`title`, `award_amount`,
     or `deadline`) is missing/unparseable.
   - Uses `instructor` to enforce a structured JSON contract
     (`LLMScholarship`) and validates disciplines against the
     `clinical_discipline` ENUM.
3. **Dedup + auto-archival** (`scrapers/runner.py`)
   - Upserts by `(provider + title)` to prevent duplicates.
   - On upsert, if `deadline < today`, sets `is_archived = True` and
     `estimated_next_cycle = deadline + 1 year`.
   - `archive_expired(db)` also bulk-archives any pre-existing expired rows.

### CLI

```bash
# Scrape all default sources and persist to the database
python -m scrapers.runner --target=all

# Scrape a single URL (dry run, no DB writes)
python -m scrapers.runner --target=https://www.pharmacist.com/... --dry-run

# Run as a daily scheduler (blocks; runs at 03:00 local time by default)
python -m scrapers.runner --schedule
python -m scrapers.runner --schedule --hour 4 --minute 30
```

### Adding sources

Edit `scrapers/sources.py`, or set `GRANTRX_SOURCES_JSON` to a JSON file:

```json
[
  {"provider": "Example Foundation", "url": "https://example.org/scholarships"}
]
```

### Playwright (optional, for JS-heavy pages)

```bash
playwright install chromium
```

The fetcher uses `httpx` first and only falls back to Playwright when the
response looks like a JS-only shell.
