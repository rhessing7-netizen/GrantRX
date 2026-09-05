# GrantRx — Intelligent Scholarship & Financial Planning Platform for Healthcare Students

> Combating clinical education debt through verified discovery, debt amortization planning, and structured application coaching for pharmacy, nursing, medical, and allied health students.

[![Tests](https://img.shields.io/badge/tests-184%20passing-brightgreen)](#testing)
[![License](https://img.shields.io/badge/license-proprietary-blue)](#license)
[![Compliance](https://img.shields.io/badge/compliance-audit%20ready-success)](docs/compliance/SECURITY_AUDIT_SUMMARY.md)

---

## Table of Contents

- [Mission](#mission)
- [Core Features & Capabilities](#core-features--capabilities)
- [Design System & Tokens](#design-system--tokens-breeze-palette)
- [Tech Stack & Infrastructure](#tech-stack--infrastructure)
- [Database Migrations Catalog](#database-migrations-catalog)
- [Local Development & Testing](#local-development--testing)
- [Security & Compliance](#security--compliance)
- [License](#license)

---

## Mission

Healthcare students graduate with an average of $200,000+ in clinical education debt, yet billions in scholarship funding go unclaimed each year due to discovery friction, fragmented application tracking, and lack of structured essay coaching. **GrantRx** solves this by providing:

1. **Verified Discovery** — A three-tier scraper pipeline ingests scholarships from community foundations, state agencies, hospital systems, national associations, and local providers, then matches them to student profiles using a weighted multi-variable scoring engine.
2. **Debt-Amortization Planning** — An interactive college financial planner calculates the true Cost of Attendance (COA), projects 10-year loan amortization, and tracks a 3x COA scholarship application cushion to minimize borrowing.
3. **Structured Application Coaching** — An AI Statement Coach generates 4-part essay outlines tailored to each provider's mission and core values, ensuring students articulate alignment without the LLM writing the essay for them.

---

## Core Features & Capabilities

### Clinical Discipline & MSA Match Engine

A weighted multi-variable scoring algorithm ranks scholarships by student fit:

| Criterion | Weight | Description |
|-----------|--------|-------------|
| Credential match | +25% | PharmD, BSN, MD, DPT, etc. |
| GPA threshold | +20% | Minimum GPA requirement |
| SAI (Student Aid Index) | +20% | Need-based eligibility ceiling |
| Geography / Metro | +15% | State and MSA (metropolitan statistical area) restrictions |
| Professional affiliations | +20% | Required memberships or honor society status |

- Results are sorted by score (0–100) and returned with **missing-criteria chips** so students can see exactly what they lack.
- Tier-gating masks low-ranked results for free-tier users, with upgrade prompts for full visibility.
- Metro matching supports both MSA names (e.g., "Cleveland-Elyria") and CBSA codes (e.g., `cbsa:17460`).

### 3-Tier Web Scraper Pipeline

| Tier | Technology | Use Case |
|------|-----------|----------|
| **Deterministic** | BeautifulSoup4 | Fast parsing of known page structures (listing tables, JSON-LD) |
| **Dynamic** | Playwright (Chromium) | JavaScript-rendered pages, infinite scroll, interactive portals |
| **LLM Fallback** | OpenAI gpt-4o-mini / LiteLLM | Unstructured pages with no deterministic match; structured JSON via `instructor` |

- Automatic deadline rollover: expired scholarships are archived with `estimated_next_cycle` set to the next year.
- Deduplication by title + portal URL prevents duplicate records across listing pages.
- Provider alignment extraction: the LLM fallback identifies provider type, mission, core values, and whether the award is local to a specific community.

### College Financial Planner & Debt Simulator

An interactive budget sheet covering direct educational costs, living expenses, and income:

- **Direct Educational:** Tuition, books/supplies, clinical lab fees
- **Living & Personal:** Housing, food, utilities, transportation, health insurance, personal
- **Income:** Family contribution, work-study wages, other grants
- **Loan Configuration:** Program years, interest rate

Computed metrics:

| Metric | Formula |
|--------|---------|
| Cost of Attendance (COA) | Direct educational + Living/personal |
| Net Unfunded Annual | COA − Non-loan income − Planned scholarships |
| 3x Cushion | 3 × COA (target scholarship application volume) |
| 5x Safety Buffer | 5 × COA (stretch goal) |
| Cushion Progress | (Planned scholarships ÷ 3x Cushion) × 100% |
| Estimated Total Debt | Net Unfunded × Program years |
| Monthly Loan Payment | Standard 10-year amortization at configured interest rate |
| Lifetime Interest | (Monthly payment × 120) − Principal |

### Calendar & Multi-Tool Export Engine

One-click export of planned scholarship deadlines to multiple productivity tools:

| Export | Format | Standard |
|--------|--------|----------|
| **Google Calendar** | Web intent URL | `calendar.google.com/render?action=TEMPLATE` with all-day date encoding |
| **Apple / Outlook Calendar** | `.ics` feed | RFC 5545 with `BEGIN:VEVENT`, `URL`, and `VALARM` (7-day pre-deadline reminder via `TRIGGER:-P7D`) |
| **Asana Project** | `.csv` download | RFC 4180 with headers: `Task Name,Due Date,Description,Notes,Section/Column,Tags` |

All exports are authenticated and scoped to the current user's planned or tracked scholarships.

### AI Statement Coach

A structured 4-part essay outliner that helps students craft compelling personal statements without writing the essay for them:

| Section | Focus |
|---------|-------|
| **Part 1: Personal Story & Upbringing** | Origin, family background, lived experiences |
| **Part 2: Work & Volunteer Track Record** | Clinical, shadowing, and community service experience |
| **Part 3: Academic Foundation & Citations** | Coursework, research, topics of interest |
| **Part 4: Future Service & Community Impact** | How the student will give back, aligned with the provider's mission |

- **Guardrail:** The system prompt explicitly instructs the LLM to generate only structured bullet points, estimated word counts, and coaching tips — never completed essay prose.
- Each section includes 3–5 talking points and 2–3 coaching tips tailored to the provider's extracted mission and core values.
- A pre-submission checklist is generated with each outline.
- Outlines can be appended to the application vault notes as structured Markdown with a single click.

### Application Vault & Kanban Board

A 4-column drag-and-drop application tracker:

| Column | Status |
|--------|--------|
| Saved | Initial bookmark |
| In Progress | Actively applying |
| Submitted | Application sent |
| Archived | Completed or expired |

Per-scholarship vault features:

- **Application notes** — Free-text notes with AI outline append support
- **Document vault** — Links to Google Drive, Dropbox, or other file storage (name, URL, type, upload date)
- **Progress checklist** — Customizable checklist with completion percentage bar
- **Inline Google Calendar sync** — One-click deadline import beside each planned scholarship

---

## Design System & Tokens (Breeze Palette)

GrantRx uses a calming, healthcare-inspired color palette called **Breeze**, paired with a serif/sans-serif typography pairing for warmth and clarity.

### Colors

| Token | Hex | Usage |
|-------|-----|-------|
| `aquamarine` | `#73FBD3` | Primary accent, success states, cushion meter fill |
| `neonIce` | `#44E5E7` | Secondary accent, active states |
| `skyAqua` | `#59D2FE` | Drag-drop target highlighting, info badges |
| `blueEnergy` | `#4A8FE7` | Links, mission alignment callouts |
| `crayolaBlue` | `#5C7AFF` | Primary buttons, focus rings |
| `surfaceBg` | — | App background (theme-dependent) |
| `cardBg` | — | Card surfaces (theme-dependent) |
| `textPrimary` | — | Primary text (theme-dependent) |
| `textSecondary` | — | Secondary text (theme-dependent) |

### Typography

| Font | Role | Source |
|------|------|--------|
| **Fraunces** | Headings (serif) | `next/font/google` |
| **Sora** | Body (sans-serif) | `next/font/google` |

---

## Tech Stack & Infrastructure

### Frontend

| Technology | Version | Purpose |
|-----------|---------|---------|
| Next.js | 16.3.3 (App Router) | React framework with Turbopack |
| React | 19.2.8 | UI library |
| TypeScript | 5.x | Type safety |
| Tailwind CSS | 4.x | Utility-first styling with Breeze tokens |
| @dnd-kit | 6.x / 8.x | Drag-and-drop for Kanban board |

**Hosted on:** Vercel (auto-deploy from `main`)

### Backend

| Technology | Version | Purpose |
|-----------|---------|---------|
| FastAPI | 0.115.0 | Async API framework |
| SQLAlchemy | 2.0.36 | ORM and database models |
| Pydantic | 2.10+ | Schema validation and serialization |
| Playwright | 1.55+ | Dynamic JavaScript rendering for scrapers |
| BeautifulSoup4 | 4.12.3 | Deterministic HTML parsing |
| OpenAI / Instructor | 2.20+ / 1.14+ | Structured LLM extraction and essay coaching |
| LiteLLM | 1.94.0 | Alternative LLM backend (Anthropic, Groq, etc.) |
| Stripe | 11.4.0 | Subscription billing and webhook handling |
| PyJWT | 2.10.0 | JWT verification for Supabase Auth |

**Hosted on:** Render (auto-deploy from `main`)

### Database & Authentication

| Service | Purpose |
|---------|---------|
| Supabase (PostgreSQL) | Primary database with Row-Level Security (RLS) on all user-facing tables |
| Supabase Auth | JWT-based authentication with email/password and OAuth (Google, GitHub) |

### Third-Party Services

| Service | Purpose |
|---------|---------|
| Stripe | Subscription billing (free/premium tiers), checkout sessions, webhook events |
| Resend | Deadline digest email alerts (14-day window, marketing opt-in gated) |
| OpenAI gpt-4o-mini | Structured scholarship extraction and AI essay outline generation |

### Scheduled Workflows (GitHub Actions)

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| `scheduled_scrape.yml` | Daily | Run scholarship scrapers across all source categories |
| `scheduled_ingestion.yml` | Daily | Ingest scraped data, repair incomplete records, send deadline digests |

---

## Database Migrations Catalog

All migrations are forward-only, idempotent (using `IF NOT EXISTS` guards), and stored in `backend/migrations/`.

| Migration | Description |
|-----------|-------------|
| `001_initial_schema.sql` | Core tables: profiles, scholarships, user_scholarships |
| `002_stripe_and_feed_token.sql` | Stripe subscription fields and calendar feed token |
| `003_add_user_identity_and_consent.sql` | User identity, terms/privacy consent timestamps |
| `004_multi_select_disciplines_credentials.sql` | Multi-select arrays for disciplines and credentials |
| `005_add_metro_restrictions.sql` | MSA/CBSA metro restriction support on scholarships |
| `006_add_metro_area_to_profiles.sql` | Metro area field on student profiles |
| `007_add_database_indexes.sql` | Performance indexes on key query columns |
| `008_add_is_dismissed_to_user_scholarships.sql` | Dismissal flag for discovery feed curation |
| `009_add_documents_and_checklist_to_user_scholarships.sql` | Application vault: documents (JSONB) and checklist (JSONB) |
| `010_add_financial_planner.sql` | Student college budget table with cost, income, and loan fields |
| `011_add_provider_alignment_and_local_fields.sql` | Provider type, mission, core values, is_local, target_community |

---

## Local Development & Testing

### Prerequisites

- Python 3.12+
- Node.js 20+
- PostgreSQL 15+ (or Supabase project URL)
- Git

### Backend Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# Configure environment
cp .env.example .env
# Edit .env with your DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, etc.

# Apply migrations (if using a fresh database)
python -c "from app.database import engine; from sqlalchemy import text; ..."
# Or apply individual migration SQL files via psql / Supabase dashboard

# Start the API
uvicorn app.main:app --reload --port 8000
```

### Frontend Setup

```bash
cd frontend
npm install

# Configure environment
cp .env.example .env.local
# Edit .env.local with NEXT_PUBLIC_API_URL (default: http://localhost:8000)

# Start the dev server
npm run dev
```

### Testing

<a id="testing"></a>

#### Backend Test Suite (184 tests)

```bash
python -m pytest backend/tests
```

Expected output:

```
====================== 184 passed, 273 warnings in 3.21s ======================
```

Test coverage by domain:

| Test File | Tests | Domain |
|-----------|-------|--------|
| `test_archiver.py` | 8 | Scholarship archival and dedup |
| `test_auth.py` | 10 | JWT middleware and dev-mode auth |
| `test_billing.py` | 18 | Stripe checkout and webhook handling |
| `test_digest.py` | 13 | Deadline digest worker |
| `test_dismiss.py` | 8 | Scholarship dismiss/undismiss and feed filtering |
| `test_exports.py` | 21 | GCal URL, Asana CSV, ICS feed exports |
| `test_financial_planner.py` | 19 | Budget calculations and loan amortization |
| `test_local_discovery.py` | 23 | Provider alignment and local discovery fields |
| `test_matcher.py` | 16 | Scholarship matching algorithm |
| `test_outline.py` | 20 | AI essay outline generation |
| `test_smoke_e2e.py` | 19 | End-to-end launch smoke tests |
| `test_vault.py` | 9 | Application vault PATCH operations |

#### Frontend Type Check

```bash
cd frontend
npx tsc --noEmit
```

Expected output: **0 errors** (clean exit)

---

## Security & Compliance

GrantRx maintains investor-grade compliance documentation in [`docs/compliance/`](docs/compliance/):

| Document | Description |
|----------|-------------|
| [Access Control Policy](docs/compliance/ACCESS_CONTROL_POLICY.md) | RBAC, MFA enforcement, credential rotation |
| [Incident Response Plan](docs/compliance/INCIDENT_RESPONSE_PLAN.md) | Sev-1 to Sev-4 levels, 5-step lifecycle, 72-hour notification |
| [Data Protection Policy](docs/compliance/DATA_PROTECTION_POLICY.md) | Data classification, encryption, FERPA/HIPAA, RLS |
| [Change Management Policy](docs/compliance/CHANGE_MANAGEMENT_POLICY.md) | Git workflow, CI/CD, rollback procedures |
| [Security Audit Summary](docs/compliance/SECURITY_AUDIT_SUMMARY.md) | Audit readiness checklist and verification status |

### Key Security Controls

- **Row-Level Security (RLS):** Enabled on `profiles`, `user_scholarships`, and `student_college_budgets` — users can only access their own data.
- **Dependabot:** Weekly vulnerability scans for npm (`/frontend`), pip (`/backend`), and GitHub Actions. Configured in [`.github/dependabot.yml`](.github/dependabot.yml).
- **Secret Scanning:** GitHub push protection blocks commits containing known secret patterns.
- **Encryption:** AES-256 at rest (Supabase), TLS 1.3 in transit (Vercel + Render).
- **MFA:** Mandatory across all admin services (GitHub, Supabase, Render, Vercel, Stripe).
- **Test Gate:** All 184 backend tests and the frontend TypeScript check must pass before any PR merges to `main`.

---

## License

Proprietary. © 2026 GrantRx. All rights reserved.

---

<p align="center">
  <strong>GrantRx</strong> — Intelligent Scholarship & Financial Planning Platform for Healthcare Students
</p>
