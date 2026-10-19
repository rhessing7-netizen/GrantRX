#!/usr/bin/env python3
"""Controlled public_description backfill — EdFintia catalog.

Generates grounded public-facing descriptions for existing scholarship
records and, on explicit approval, persists reviewed text. Evolved from
the 10-record pilot; this is THE canonical tool (see
docs/PUBLIC_DESCRIPTION_BACKFILL.md).

Safety contract
---------------
- DRY RUN is the default. Nothing writes without ``--apply``.
- ``--apply`` requires ``--results`` — it writes ONLY the reviewed text
  stored in the dry-run JSON, verbatim. It never calls the LLM.
- Hard batch cap 25 (``--allow-over-limit`` for exceptional overrides
  only); default limit 10.
- Staging identity is required: the DB URL must contain the staging
  project ref and must NOT be a production ref or localhost.
- Updates are guarded ``WHERE public_description IS NULL`` — populated
  rows (including the six approved pilot records) are NEVER touched.
- Per-record failures are isolated; an LLM authentication failure aborts
  the run immediately (a credential problem cannot fix itself).

Pipeline (identical semantics to the production extraction path)
----------------------------------------------------------------
fetch (robots-aware) -> classify_page -> large-source isolation when the
page text exceeds the single-opportunity bound -> LLM extract ->
deterministic verification (``attach_verification`` / ``_description_grounded``)
-> low-information gate -> approval-only writes.

Failure taxonomy (reported per record, never persisted)
-------------------------------------------------------
SUCCESS / INSUFFICIENT_SOURCE / LOW_INFORMATION / SOURCE_FETCH_FAILED /
TARGET_NOT_ISOLATED / LLM_AUTH_FAILED / LLM_RATE_LIMITED /
LLM_CONTEXT_LIMIT / LLM_OTHER_ERROR / SANITIZER_REJECTED /
GROUNDING_REJECTED / ALREADY_HAS_DESCRIPTION

Retry policy: bounded retries for transient fetch (timeout/network/5xx),
provider rate limits, and transient provider errors. Never retried:
auth (aborts the run), permanent fetch outcomes (robots/4xx),
context-limit (fixed by isolation, not repetition), grounding/low-info/
sanitizer rejections, and already-populated rows.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv

load_dotenv(BACKEND / ".env", override=False)
if (BACKEND / "staging.env").exists():
    load_dotenv(BACKEND / "staging.env", override=False)

import psycopg  # noqa: E402

from scrapers.extraction import (  # noqa: E402
    attach_verification,
    classify_page,
    isolate_target_evidence,
)
from scrapers.fetcher import fetch_result  # noqa: E402
from scrapers.llm_parser import (  # noqa: E402
    LLM_ERR_AUTH,
    LLM_ERR_CONTEXT,
    LLM_ERR_OTHER,
    LLM_ERR_RATE_LIMIT,
    SINGLE_MAX_CHARS,
    extract_opportunities_with_llm,
)
from scrapers.utils.identity import normalize_identity_text  # noqa: E402
from scrapers.verification import (  # noqa: E402
    description_low_information,
    html_to_text,
)

# --- failure taxonomy -------------------------------------------------------
OUTCOME_SUCCESS = "SUCCESS"
OUTCOME_INSUFFICIENT = "INSUFFICIENT_SOURCE"
OUTCOME_LOW_INFORMATION = "LOW_INFORMATION"
OUTCOME_FETCH_FAILED = "SOURCE_FETCH_FAILED"
OUTCOME_NOT_ISOLATED = "TARGET_NOT_ISOLATED"
OUTCOME_LLM_AUTH = "LLM_AUTH_FAILED"
OUTCOME_LLM_RATE_LIMIT = "LLM_RATE_LIMITED"
OUTCOME_LLM_CONTEXT = "LLM_CONTEXT_LIMIT"
OUTCOME_LLM_OTHER = "LLM_OTHER_ERROR"
OUTCOME_SANITIZER = "SANITIZER_REJECTED"
OUTCOME_GROUNDING = "GROUNDING_REJECTED"
OUTCOME_ALREADY = "ALREADY_HAS_DESCRIPTION"

# fetch outcomes that warrant a bounded retry (transient); 4xx/robots do not
_RETRYABLE_FETCH = {"timeout", "network_error", "transient_http"}
_MAX_RETRIES = 2  # attempts per record = 1 + _MAX_RETRIES
_BACKOFF_S = (2.0, 8.0)

BATCH_CAP = 25
DEFAULT_LIMIT = 10


def staging_db_url() -> str:
    url = os.environ.get("TARGET_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if "bcsniblbexmugkypbrff" in url or "localhost" in url or "5433" in url:
        sys.exit("Refusing non-staging / production database target")
    if "cacpuytmmwlilidadklu" not in url:
        sys.exit("Could not positively identify staging project in TARGET_DATABASE_URL")
    return url


CANDIDATE_SQL = """
    SELECT id, title, provider, source_url, portal_url, award_amount,
           deadline, verification_status, lifecycle_status
      FROM scholarships
     WHERE public_description IS NULL
       AND source_url IS NOT NULL
       AND lifecycle_status = 'published'
       AND verification_status IS DISTINCT FROM 'needs_review'
     ORDER BY title
"""

ID_SQL = """
    SELECT id, title, provider, source_url, portal_url, award_amount,
           deadline, verification_status, lifecycle_status,
           (public_description IS NOT NULL) AS _has_description
      FROM scholarships
     WHERE id = ANY(%s)
     ORDER BY title
"""


def select_candidates(cur, limit: int):
    cur.execute(CANDIDATE_SQL + " LIMIT %s", (limit,))
    return [dict(zip([d.name for d in cur.description], r)) for r in cur.fetchall()]


def select_by_ids(cur, ids):
    # No NULL filter: explicitly named populated rows must report
    # ALREADY_HAS_DESCRIPTION, not silently vanish from the audit.
    cur.execute(ID_SQL, (ids,))
    return [dict(zip([d.name for d in cur.description], r)) for r in cur.fetchall()]


def _match_extract(extracts, title):
    """Deterministic identity match — never a fuzzy guess at which extract
    is ours; a miss is classified INSUFFICIENT_SOURCE, not resolved."""
    tn = normalize_identity_text(title)
    matches = [
        e for e in extracts
        if normalize_identity_text(e.title or "") == tn
    ]
    return matches[0] if len(matches) == 1 else None


def _llm_outcome(diag: dict) -> str:
    return {
        LLM_ERR_AUTH: OUTCOME_LLM_AUTH,
        LLM_ERR_RATE_LIMIT: OUTCOME_LLM_RATE_LIMIT,
        LLM_ERR_CONTEXT: OUTCOME_LLM_CONTEXT,
    }.get(diag.get("error_kind", ""), OUTCOME_LLM_OTHER)


async def _attempt_for(row):
    """One generation attempt. Returns (record_dict, classification, usage).

    Never raises for content failures — every outcome is classified so a
    batch survives per-record problems.
    """
    out = {
        "id": str(row["id"]),
        "title": row["title"],
        "provider": row["provider"],
        "source_url": row["source_url"],
    }
    res = await fetch_result(row["source_url"])
    if not res.ok:
        out["fetch_outcome"] = res.outcome
        out["retryable"] = res.outcome in _RETRYABLE_FETCH
        return out, OUTCOME_FETCH_FAILED, None
    out["fetch_outcome"] = "ok"

    cls = classify_page(res.text or "", row["source_url"])
    out["page_kind"] = cls.kind
    text = html_to_text(res.text or "")
    title = row["title"] or ""
    llm_input, mode, max_items = res.text, cls.kind, 12
    evidence = text

    if len(text) > SINGLE_MAX_CHARS:
        # Large aggregate/listing page — isolate the target before the call
        # (pilot finding: full-page listing input blew the output-token path).
        isolated = isolate_target_evidence(text, title, cls.items)
        if isolated is None:
            return out, OUTCOME_NOT_ISOLATED, None
        llm_input, mode, max_items = isolated, "single_opportunity", 1
        evidence = isolated
        out["isolated_input_chars"] = len(isolated)

    diag: dict = {}
    extraction = await extract_opportunities_with_llm(
        llm_input, row["source_url"], mode=mode, max_items=max_items,
        diagnostics=diag,
    )
    if extraction is None:
        out["llm_error"] = diag.get("error_msg")
        return out, _llm_outcome(diag), diag.get("usage")

    match = _match_extract(extraction.extracts, title)
    if match is None:
        return out, OUTCOME_INSUFFICIENT, diag.get("usage")
    out["extract_title"] = match.title
    out["evidence"] = evidence[:2400]

    verified = attach_verification(match, text=evidence, source_url=row["source_url"])
    out["verified_fields"] = getattr(verified, "verified_fields", {})
    out["public_description"] = verified.public_description
    if verified.public_description is None:
        if match.public_description is not None:
            # sanitize passed but grounding destroyed the narrative
            return out, OUTCOME_GROUNDING, diag.get("usage")
        if getattr(verified, "public_description_dropped", False):
            return out, OUTCOME_SANITIZER, diag.get("usage")
        return out, OUTCOME_INSUFFICIENT, diag.get("usage")

    reason = description_low_information(
        verified.public_description,
        title=row["title"] or "",
        provider=row["provider"] or "",
        evidence_text=evidence,
    )
    if reason:
        out["low_info_reason"] = reason
        out["candidate_description"] = verified.public_description
        out["public_description"] = None
        return out, OUTCOME_LOW_INFORMATION, diag.get("usage")
    return out, OUTCOME_SUCCESS, diag.get("usage")


async def generate_for(row):
    """Bounded-attempt wrapper. Auth failure aborts the whole run — raise."""
    attempts = []
    for attempt in range(1 + _MAX_RETRIES):
        out, classification, usage = await _attempt_for(row)
        out["usage"] = usage
        attempts.append({"attempt": attempt + 1, "classification": classification})
        out["attempts"] = attempts
        out["classification"] = classification
        if classification == OUTCOME_LLM_AUTH:
            raise _AuthAbort(out["id"])
        # fetch outcome decides retryability for fetch failures; LLM classes
        # carry their own retryability
        retryable = classification in (OUTCOME_LLM_RATE_LIMIT, OUTCOME_LLM_OTHER) or (
            classification == OUTCOME_FETCH_FAILED and out.get("retryable")
        )
        if retryable and attempt < _MAX_RETRIES:
            time.sleep(_BACKOFF_S[attempt])
            continue
        return out
    return out


class _AuthAbort(Exception):
    pass


def _quality_gate(rec):
    return "pass" if rec.get("public_description") else "none"


async def cmd_dry_run(args):
    rows = []
    conn = psycopg.connect(staging_db_url())
    try:
        with conn.cursor() as cur:
            rows = select_by_ids(cur, args.ids) if args.ids else select_candidates(cur, args.limit)
    finally:
        conn.close()
    if not rows:
        sys.exit("no candidates matched")

    llm_calls = 0
    prompt_tokens = completion_tokens = 0
    out = []
    for r in rows:
        rec = {"id": str(r["id"]), "title": r["title"], "provider": r["provider"],
               "source_url": r["source_url"], "public_description": None}
        if not r.get("source_url"):
            rec["classification"] = OUTCOME_INSUFFICIENT
        elif r.get("_has_description"):
            rec["classification"] = OUTCOME_ALREADY
        else:
            try:
                rec = await generate_for(r)
            except _AuthAbort:
                print(
                    f"AUTH FAILURE — aborting run (no writes): {rec['title']}",
                    file=sys.stderr,
                )
                sys.exit(3)
            usage = rec.get("usage") or {}
            if usage.get("prompt_tokens") is not None:
                llm_calls += 1
                prompt_tokens += usage["prompt_tokens"] or 0
                completion_tokens += usage["completion_tokens"] or 0
            elif str(rec.get("classification") or "").startswith("LLM_"):
                llm_calls += 1
        rec["gate"] = _quality_gate(rec)
        out.append(rec)
        print(f"[{rec['classification']:>22}] {r['title'][:60]} ({str(r['provider'])[:30]})")

    Path(args.out).write_text(json.dumps(out, indent=2))
    passed = sum(1 for x in out if x["gate"] == "pass")
    classes = {}
    for x in out:
        classes[x["classification"]] = classes.get(x["classification"], 0) + 1
    print(f"\nwrote {args.out}: {len(out)} records, {passed} gated-pass")
    print(f"classifications: {json.dumps(classes, sort_keys=True)}")
    print(f"llm_calls={llm_calls} prompt_tokens={prompt_tokens} completion_tokens={completion_tokens}")


def cmd_apply(args):
    approved = json.loads(Path(args.results).read_text())
    if args.ids:
        wanted = set(args.ids)
        approved = [a for a in approved if str(a.get("id")) in wanted]
    rows = [a for a in approved
            if a.get("classification") == OUTCOME_SUCCESS and a.get("public_description")]
    if not rows:
        sys.exit("no approved descriptions in results")
    print(f"applying {len(rows)} reviewed descriptions (null-guarded)")

    conn = psycopg.connect(staging_db_url())
    try:
        with conn.cursor() as cur:
            applied = 0
            for a in rows:
                cur.execute(
                    "UPDATE scholarships SET public_description=%s "
                    "WHERE id=%s AND public_description IS NULL",
                    (a["public_description"], a["id"]),
                )
                if cur.rowcount:
                    applied += 1
                    print(f"  wrote {a['id']} {a['title'][:50]}")
                else:
                    print(f"  SKIP  {a['id']} already populated or missing")
        conn.commit()
    finally:
        conn.close()
    print(f"{applied}/{len(rows)} descriptions written")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p.add_argument("--ids", nargs="*", help="explicit scholarship ids")
    p.add_argument("--allow-over-limit", action="store_true",
                   help="permit batches above the hard cap of 25 (exceptional use)")
    p.add_argument("--out", default="pilot_description_results.json")
    p.add_argument("--apply", action="store_true",
                   help="WRITE approved descriptions (requires --results)")
    p.add_argument("--results", help="dry-run results JSON to apply verbatim")
    args = p.parse_args()

    if args.limit > BATCH_CAP and not args.allow_over_limit:
        sys.exit(f"limit {args.limit} exceeds hard cap {BATCH_CAP}; pass --allow-over-limit")
    if args.ids and len(args.ids) > BATCH_CAP and not args.allow_over_limit:
        sys.exit(f"{len(args.ids)} ids exceeds hard cap {BATCH_CAP}")

    if args.apply:
        if not args.results:
            sys.exit("--apply requires --results <dry-run-json>")
        cmd_apply(args)
    else:
        asyncio.run(cmd_dry_run(args))


if __name__ == "__main__":
    main()
