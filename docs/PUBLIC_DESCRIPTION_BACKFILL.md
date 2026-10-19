# PUBLIC_DESCRIPTION BACKFILL — Engineering Runbook

Canonical tool: `backend/scripts/backfill_public_description.py`
Field: `scholarships.public_description` (migration 029, nullable TEXT).

## Purpose

Populate a consumer-facing, plain-language description for existing catalog
records using ONLY source-grounded extraction. Every persisted narrative
must be traceable to evidence on the record's own source page.

## Source-of-truth pipeline

The tool reuses the production extraction path — it is not a parallel
pipeline:

1. `scrapers.fetcher.fetch_result` — robots-aware, paced source retrieval.
2. `scrapers.extraction.classify_page` — page kind + named-opportunity labels.
3. **Large-source isolation** — when page text exceeds `SINGLE_MAX_CHARS`
   (12k), `isolate_target_evidence` extracts only the target's bounded
   segment(s) (sibling labels delimit boundaries) plus the page-level
   preamble preceding the first label. Ambiguous or absent target →
   classified NULL, never a guess.
4. `extract_opportunities_with_llm` — same prompt/contract as production
   (`public_description` is source-grounded by prompt; null allowed).
5. `_sanitize_description` — URL strip, length hygiene.
6. `attach_verification` / `_description_grounded` — numeric claims must be
   locatable in scoped evidence; ungrounded prose → NULL.
7. `description_low_information` — rejects restatement/generic-filler
   narratives (pilot FSAG case) via deterministic source-aware signals:
   sparse evidence, title/provider restatement, unsupported substantive
   terms. Short/number-free legitimate narratives pass.

## Dry-run workflow (DEFAULT — no writes)

```bash
cd backend
TARGET_DATABASE_URL=... python scripts/backfill_public_description.py \
    [--limit 10] [--ids <uuid>...] --out results.json
```

- Emits `results.json`: per record — classification, attempts, candidate /
  proposed description, evidence excerpt, low-info reason, token usage.
- Selection: `public_description IS NULL AND source_url IS NOT NULL AND
  lifecycle_status='published' AND verification_status <> 'needs_review'`,
  `ORDER BY title` (deterministic).

## Review workflow

- **Next batch: 100% manual review** of every generated description before
  write. Compare each narrative against the artifact's evidence excerpt.
- Reject by removing the record's SUCCESS classification (or delete the
  row) in a reviewed copy of the artifact.
- No automatic approval threshold exists yet — quality data comes first.

## Apply workflow

```bash
python scripts/backfill_public_description.py --apply \
    --results <reviewed>.json [--ids <uuid>...]
```

- Writes ONLY `classification=SUCCESS` rows' `public_description`, verbatim —
  no regeneration, zero LLM calls.
- Guarded update: `WHERE id=? AND public_description IS NULL`.
- A row already populated (concurrent write, pilot record) is reported
  `SKIP` — never overwritten.

## Staging safeguards / production refusal

- DB URL must positively contain staging ref `cacpuytmmwlilidadklu`.
- Refuses: production ref `bcsniblbexmugkypbrff`, localhost, `:5433`
  (frozen local catalog).
- Batch cap: **25** hard limit; default `--limit 10`. `>25` requires
  `--allow-over-limit` — exceptional use only.
- Resumable: rerun is safe — populated rows classify
  `ALREADY_HAS_DESCRIPTION`; artifacts are stable JSON for review/apply.

## Failure taxonomy (reported, never persisted)

`SUCCESS` · `INSUFFICIENT_SOURCE` · `LOW_INFORMATION` ·
`SOURCE_FETCH_FAILED` · `TARGET_NOT_ISOLATED` · `LLM_AUTH_FAILED` ·
`LLM_RATE_LIMITED` · `LLM_CONTEXT_LIMIT` · `LLM_OTHER_ERROR` ·
`SANITIZER_REJECTED` · `GROUNDING_REJECTED` · `ALREADY_HAS_DESCRIPTION`

## Retry policy

Bounded: 1 + 2 attempts, backoff 2s/8s.
Retryable: transient fetch (`timeout`, `network_error`, `transient_http`),
`LLM_RATE_LIMITED`, `LLM_OTHER_ERROR`.
Never retried: permanent fetch outcomes (robots/4xx/access_denied),
`LLM_CONTEXT_LIMIT` (isolation is the fix, not repetition), grounding /
sanitizer / low-information rejections, `TARGET_NOT_ISOLATED`,
`ALREADY_HAS_DESCRIPTION`.
**`LLM_AUTH_FAILED` aborts the entire run immediately** — a credential
problem cannot fix itself per record and retrying wastes spend.

## No-overwrite policy

`public_description` is write-once per record. The six approved pilot
descriptions are frozen: selection filters `IS NULL`, apply guards
`IS NULL`, and `--ids` against a populated row reports
`ALREADY_HAS_DESCRIPTION` without touching it.

## Manual review requirement

Writes only ever come from a reviewed dry-run artifact. `--apply` with
`--results` is the sole write path.

## Secret handling — WARNING

`backend/.env.example` is tracked and must never contain real
credentials. **TRACKED SECRET CLEANUP TODO REMAINS OPEN** — a key was
accidentally placed there (rotation owner-deferred). Never stage/commit/
display it. `backend/.env` and `backend/staging.env` are gitignored —
keep them that way. Diagnostics never log secrets.
