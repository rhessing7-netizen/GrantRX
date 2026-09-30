"""Catalog Review & Clearance Engine (Q1).

Re-evaluates persisted ``needs_review`` opportunities against their current
authoritative evidence and clears the ones that satisfy today's verification
rules. This is a throughput system, NOT a trust-policy relaxation: every
clearance goes through the exact same verification pipeline extraction uses
(``scrapers.extraction.attach_verification`` + ``scrapers.verification``),
and claims that authoritative evidence cannot support are degraded to honest
unknowns — the same transform the extractor itself performs
(``_deadline_year_supported``, ``_canonical_disciplines``).

Responsibilities:

  Phase 1  ``classify_record`` / ``classify_backlog``
           deterministic review-reason taxonomy derived from the actual
           verification logic (persisted ``verified_fields`` verdicts plus
           the structural predicates extraction applies).
  Phase 2  ``reevaluate_record``
           safe re-evaluation: re-run the real verification on re-fetched
           authoritative evidence; degrade unsupported optional claims;
           keep the record gated when evidence remains insufficient.
  Phase 3  bounded evidence enrichment: the record's stored ``source_url``
           and (when distinct) ``portal_url`` are fetched through the shared
           C6 FetchSession — robots, pacing, access_denied, and all existing
           host limits apply unchanged. No guessed URLs, no aggregators, no
           stealth, no CAPTCHA bypass, no broad search.
  Phase 4  ``queue_category`` / ``review_queue``
           programmatic queue: AUTO_RECHECK | EVIDENCE_FETCH | HUMAN_REVIEW
           | BLOCKED_SOURCE, derived from persisted state (no migration).

CLI:

  python -m scrapers.review --classify        # backlog forensics only
  python -m scrapers.review --queue           # queue listing (derived)
  python -m scrapers.review --run [--dry-run] [--limit N] [--include-archived]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from .extraction import (
    _ANY_FIELD_EVIDENCE,
    _EDU_FUNDING_TERM,
    _FUND_ACCOUNT_TITLE,
    _GENERIC_PROVIDER,
    _OPPORTUNITY_NOUN,
    _deadline_year_supported,
    attach_verification,
    evidence_windows,
    narrow_disciplines_to_evidence,
)
from .fetch_policy import (
    OUTCOME_OK,
    OUTCOME_NOT_MODIFIED,
    FetchResult,
    FetchSession,
    default_session,
)
from .schema import ScholarshipExtract
from .utils.page_links import normalize_link
from .verification import html_to_text

logger = logging.getLogger("scrapers.review")

# ---------------------------------------------------------------------------
# Run caps (Q1) — conservative defaults, env-overridable like the rest of the
# catalog pipeline.
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


@dataclass(frozen=True)
class ReviewLimits:
    """Global and per-record bounds for one clearance run."""

    max_pages_fetched: int = 300       # additional authoritative pages, global
    max_detail_pages_per_opportunity: int = 2  # source listing + distinct portal
    max_llm_calls: int = 150           # budgeted by policy; the engine uses 0
    fetch_timeout: float = 30.0

    @classmethod
    def from_env(cls) -> "ReviewLimits":
        return cls(
            max_pages_fetched=_env_int("Q1_MAX_PAGES", 300),
            max_detail_pages_per_opportunity=max(
                1, _env_int("Q1_MAX_DETAIL_PAGES", 2)),
            max_llm_calls=_env_int("Q1_MAX_LLM_CALLS", 150),
            fetch_timeout=float(os.getenv("CRAWLER_TIMEOUT", "30")),
        )


# ---------------------------------------------------------------------------
# Review-reason taxonomy — derived from the actual verification logic, not
# invented categories. Every reason maps to a concrete gate in
# verification.verify_extract_against_text or extraction._structural_review_flags.
# ---------------------------------------------------------------------------

UNSUPPORTED_TITLE = "unsupported_title"
UNSUPPORTED_AWARD = "unsupported_award_amount"
UNSUPPORTED_DEADLINE = "unsupported_deadline"
UNSUPPORTED_GPA = "unsupported_min_gpa"
UNSUPPORTED_ANY = "unsupported_unrestricted_claim"
FUND_TITLE_EVIDENCE = "fund_title_needs_education_evidence"
NO_OPPORTUNITY_NOUN = "title_no_opportunity_noun"
GENERIC_PROVIDER = "generic_provider"
NO_PERSISTED_EVIDENCE = "no_persisted_evidence"
# Runtime-only reasons (produced while evaluating, not classifiable pre-fetch):
TITLE_ABSENT_ON_SOURCE = "title_not_found_on_source"
SOURCE_UNVERIFIABLE = "source_unverifiable"

_FIELD_REASONS = {
    "title": UNSUPPORTED_TITLE,
    "award_amount": UNSUPPORTED_AWARD,
    "deadline": UNSUPPORTED_DEADLINE,
    "min_gpa": UNSUPPORTED_GPA,
}

# Optional assertions the engine may degrade to "unknown" — they are exactly
# the claims the extractor is allowed to leave unasserted. Identity (title),
# provider, portal URL, and restriction claims are NEVER degraded.
DEGRADABLE_REASONS = {
    UNSUPPORTED_AWARD,
    UNSUPPORTED_DEADLINE,
    UNSUPPORTED_GPA,
    UNSUPPORTED_ANY,
}

# Reasons no amount of new evidence can repair — genuine human judgment.
PERMANENT_REASONS = {
    UNSUPPORTED_TITLE,
    TITLE_ABSENT_ON_SOURCE,
    NO_OPPORTUNITY_NOUN,
    GENERIC_PROVIDER,
}

# Queue categories (Phase 4).
AUTO_RECHECK = "auto_recheck"
EVIDENCE_FETCH = "evidence_fetch"
HUMAN_REVIEW = "human_review"
BLOCKED_SOURCE = "blocked_source"
# Archived deadline_passed records are classified but not worked (Q1 policy);
# only an explicit current-cycle review (run_clearance(include_archived=True))
# may re-evaluate them.
ARCHIVED_SKIP = "archived_deadline_passed"
# Archived for a sticky reason (E4.6): a record judged a duplicate, manually
# removed, discontinued, or removed at source is never re-verified by the
# ordinary clearance engine — not even with include_archived — so backlog
# runs cannot mark junk "verified". Mirrors lifecycle's non-auto-recoverable
# archive reasons.
ARCHIVED_EXCLUDED = "archived_excluded"
EXCLUDED_ARCHIVE_REASONS = frozenset(
    {"duplicate", "manual", "discontinued", "source_removed"})
QUEUE_CATEGORIES = (AUTO_RECHECK, EVIDENCE_FETCH, HUMAN_REVIEW, BLOCKED_SOURCE)

_BLOCKED_SOURCE_HEALTH = {
    "access_denied",
    "robots_denied",
    "robots_unavailable",
    "permanent_not_found",
    "needs_url_review",
    "transient_failure",
}

_BLOCKED_FETCH_OUTCOMES = {
    "access_denied",
    "robots_denied",
    "robots_unavailable",
    "permanent_http",
    "timeout",
    "network_error",
    "transient_http",
    "invalid_url",
}


def _vf(row) -> dict:
    return dict(getattr(row, "verified_fields", None) or {})


def _is_generic_provider(provider: str) -> bool:
    return bool(_GENERIC_PROVIDER.match((provider or "").strip()))


def structural_reasons(title: str, provider: str,
                       eligible_disciplines: Sequence[str]) -> List[str]:
    """Deterministic structural gates that need no evidence text.

    Mirrors ``extraction._structural_review_flags`` conditions that are
    computable from persisted fields alone. The remaining two conditions
    (``any``-evidence, fund-education evidence) are recorded as their
    *trigger* reasons — they only resolve against fetched evidence.
    """
    reasons = []
    if not _OPPORTUNITY_NOUN.search(title or ""):
        reasons.append(NO_OPPORTUNITY_NOUN)
    if _is_generic_provider(provider):
        reasons.append(GENERIC_PROVIDER)
    return reasons


def classify_record(row) -> Tuple[List[str], List[str]]:
    """Return (reasons, evidence_checks) for one persisted needs_review row.

    ``reasons`` are blockers determinable without fetching; ``evidence_checks``
    are conditions whose satisfaction requires authoritative text
    (unrestricted-claim evidence, fund-education evidence). A record may carry
    several blockers — the taxonomy reflects every gate that fired.
    """
    reasons: List[str] = []
    checks: List[str] = []
    vf = _vf(row)

    if not vf:
        reasons.append(NO_PERSISTED_EVIDENCE)
    else:
        for fname, verdict in vf.items():
            if fname in _FIELD_REASONS and verdict == "unverified":
                reasons.append(_FIELD_REASONS[fname])

    reasons.extend(structural_reasons(
        getattr(row, "title", ""), getattr(row, "provider", ""),
        getattr(row, "eligible_disciplines", None) or []))

    discs = list(getattr(row, "eligible_disciplines", None) or [])
    if any(str(d).lower() == "any" for d in discs):
        # Extraction already established this claim lacked unrestricted
        # evidence (otherwise the record would not be gated for it when all
        # other checks pass); re-evaluation may still prove or degrade it.
        reasons.append(UNSUPPORTED_ANY)
    if _FUND_ACCOUNT_TITLE.search(getattr(row, "title", "") or ""):
        checks.append(FUND_TITLE_EVIDENCE)

    # Stable order for reporting/testing.
    order = [
        UNSUPPORTED_TITLE, UNSUPPORTED_AWARD, UNSUPPORTED_DEADLINE,
        UNSUPPORTED_GPA, UNSUPPORTED_ANY, FUND_TITLE_EVIDENCE,
        NO_OPPORTUNITY_NOUN, GENERIC_PROVIDER, NO_PERSISTED_EVIDENCE,
        TITLE_ABSENT_ON_SOURCE, SOURCE_UNVERIFIABLE,
    ]
    reasons.sort(key=order.index)
    return reasons, checks


def queue_category(row, reasons: Sequence[str], checks: Sequence[str],
                   *, source_health: Optional[str] = None) -> str:
    """Assign the record's review-queue category from persisted state.

    HUMAN_REVIEW wins over evidence paths (a hard blocker can't self-resolve);
    BLOCKED_SOURCE applies when no authoritative page can currently be
    retrieved; EVIDENCE_FETCH when a distinct authoritative detail URL exists;
    AUTO_RECHECK when re-running today's rules on the same source may clear it.
    """
    if _excluded_archive(row):
        return ARCHIVED_EXCLUDED
    if getattr(row, "lifecycle_status", "published") == "archived" and \
            getattr(row, "archive_reason", None) == "deadline_passed":
        return ARCHIVED_SKIP
    if any(r in PERMANENT_REASONS for r in reasons):
        return HUMAN_REVIEW
    if (source_health or "") in _BLOCKED_SOURCE_HEALTH:
        return BLOCKED_SOURCE
    if _distinct_portal(row):
        return EVIDENCE_FETCH
    return AUTO_RECHECK


def _excluded_archive(row) -> bool:
    return (getattr(row, "lifecycle_status", None) == "archived"
            and getattr(row, "archive_reason", None) in EXCLUDED_ARCHIVE_REASONS)


def _distinct_portal(row) -> bool:
    """True when the persisted portal URL is a different page than source_url —
    the one authoritative second page an enrichment fetch may use."""
    portal, source = getattr(row, "portal_url", "") or "", getattr(row, "source_url", "") or ""
    if not portal or not source:
        return False
    return normalize_link(portal) != normalize_link(source)


def _extract_from_row(row) -> ScholarshipExtract:
    """Rebuild the extraction record from persisted fields.

    Verification then runs on the same claims the row makes — no
    re-extraction, no LLM, no weakening. ``min_gpa`` 0.0 is the persisted
    "not asserted" representation (see runner._to_db_dict)."""
    gpa = getattr(row, "min_gpa", None)
    return ScholarshipExtract(
        title=getattr(row, "title", "") or "",
        provider=getattr(row, "provider", "") or "",
        portal_url=getattr(row, "portal_url", "") or "",
        award_amount=getattr(row, "award_amount", None),
        deadline=(row.deadline.isoformat()
                  if getattr(row, "deadline", None) else None),
        eligible_disciplines=list(getattr(row, "eligible_disciplines", None) or []),
        is_general_major=bool(getattr(row, "is_general_major", False)),
        min_gpa=gpa if gpa not in (None, 0.0) else None,
        source=getattr(row, "extraction_method", None) or "deterministic",
    )


def degrade_unsupported(extract: ScholarshipExtract,
                        field_verdicts: Dict[str, str],
                        reasons: Sequence[str]) -> List[str]:
    """Clear unsupported OPTIONAL assertions on the extract (in place).

    Returns the reason codes removed. Mirrors the extractor's own behavior —
    a value authoritative evidence cannot support is left unknown rather than
    asserted. Identity fields are never touched. ``['any']`` degrades to the
    honest unknown ``[]`` together with its ``is_general_major`` companion.
    """
    degraded: List[str] = []
    if UNSUPPORTED_AWARD in reasons and field_verdicts.get("award_amount") == "unverified":
        extract.award_amount = None
        degraded.append(UNSUPPORTED_AWARD)
    if UNSUPPORTED_DEADLINE in reasons and field_verdicts.get("deadline") == "unverified":
        extract.deadline = None
        degraded.append(UNSUPPORTED_DEADLINE)
    if UNSUPPORTED_GPA in reasons and field_verdicts.get("min_gpa") == "unverified":
        extract.min_gpa = None
        degraded.append(UNSUPPORTED_GPA)
    if UNSUPPORTED_ANY in reasons:
        extract.eligible_disciplines = []
        extract.is_general_major = False
        degraded.append(UNSUPPORTED_ANY)
    return degraded


@dataclass
class ReviewOutcome:
    """Result of re-evaluating one record."""

    action: str = "gated"            # verified | gated | blocked | skipped
    cleared: bool = False
    degraded: List[str] = field(default_factory=list)
    reasons_before: List[str] = field(default_factory=list)
    reasons_after: List[str] = field(default_factory=list)
    evidence_urls: List[str] = field(default_factory=list)
    fetch_outcomes: Dict[str, str] = field(default_factory=dict)
    queue: str = HUMAN_REVIEW
    detail: str = ""


FetchEvidenceFn = Callable[[str], Awaitable[FetchResult]]


async def reevaluate_record(
    row,
    *,
    fetch: FetchEvidenceFn,
    sibling_titles: Optional[List[str]] = None,
    source_discipline: Optional[str] = None,
    dry_run: bool = False,
) -> ReviewOutcome:
    """Re-run today's verification on one persisted record.

    ``fetch`` retrieves one authoritative page (C6 FetchSession.get in
    production; canned results in tests). ``sibling_titles`` are the titles of
    every other persisted opportunity sharing ``source_url`` — they rebuild
    the same evidence window extraction used (a listing child is verified
    only against its own segment, never a sibling's facts).
    ``source_discipline`` is the registry's curated primary_discipline for
    the record's source — it lets an over-broad area claim narrow to the
    field the source itself declares when the evidence does not veto it.

    Mutates the ORM row on success unless ``dry_run``. Never writes
    lifecycle_status, last_seen_at, identity, or linkage columns.
    """
    reasons, checks = classify_record(row)
    out = ReviewOutcome(reasons_before=list(reasons))
    if _excluded_archive(row):
        out.action = "skipped"
        out.queue = ARCHIVED_EXCLUDED
        out.detail = f"archived ({row.archive_reason}): excluded from clearance"
        return out
    extract = _extract_from_row(row)
    source_url = getattr(row, "source_url", None) or getattr(row, "portal_url", "")
    portal_url = getattr(row, "portal_url", "") or ""
    siblings = [t for t in (sibling_titles or []) if t and t != extract.title]

    # -- Stage 1: authoritative listing evidence ---------------------------
    source_res = await fetch(source_url) if source_url else None
    page_text = ""
    if source_res is not None:
        out.fetch_outcomes[source_url] = source_res.outcome
        out.evidence_urls.append(source_url)
        if source_res.ok and source_res.text:
            page_text = html_to_text(source_res.text)

    listing_evidence = ""
    title_absent_on_source = False
    if page_text:
        if siblings:
            # A listing child is verified only against its own page segment —
            # rebuilt from the sibling titles persisted for the same source.
            listing_evidence = evidence_windows(
                page_text, [extract.title, *siblings])[0]
        else:
            listing_evidence = page_text
        if not _title_on_evidence(extract.title, page_text):
            # The listing no longer carries this title — evidence moved, the
            # opportunity may have been renamed or removed. A detail page can
            # still support the record, so this only gates identity, not fetch.
            title_absent_on_source = True

    # -- Stage 2: distinct authoritative detail page (bounded) --------------
    detail_res = None
    if portal_url and normalize_link(portal_url) != normalize_link(source_url):
        detail_res = await fetch(portal_url)
        out.fetch_outcomes[portal_url] = detail_res.outcome
        out.evidence_urls.append(portal_url)

    detail_text = ""
    if detail_res is not None and detail_res.ok and detail_res.text:
        detail_text = html_to_text(detail_res.text)

    evidence = " ".join(p for p in (listing_evidence, detail_text) if p).strip()

    # -- No usable evidence at all ------------------------------------------
    if not evidence:
        any_ok = any(o in (OUTCOME_OK, OUTCOME_NOT_MODIFIED)
                     for o in out.fetch_outcomes.values())
        if not out.fetch_outcomes:
            out.action = "skipped"
            out.detail = "no URLs to fetch"
        elif any_ok:
            # Pages responded but none carried the record's title — the
            # evidence base moved. Gated for a human, not a fetch problem.
            out.action = "gated"
            out.queue = HUMAN_REVIEW
            out.reasons_after = list(dict.fromkeys(
                [*reasons, TITLE_ABSENT_ON_SOURCE]))
            out.detail = "title not found on retrieved authoritative pages"
        else:
            out.action = "blocked"
            out.queue = BLOCKED_SOURCE
            out.reasons_after = list(dict.fromkeys(
                [*reasons, SOURCE_UNVERIFIABLE]))
            out.detail = ";".join(
                f"{u} -> {o}" for u, o in out.fetch_outcomes.items())
        return out

    # -- Re-verify through the real engine ---------------------------------
    deadline_before = extract.deadline
    extract.deadline = _deadline_year_supported(extract.deadline, evidence)
    if deadline_before and extract.deadline is None:
        # Year-unsupported deadline normalized to unknown — the same claim
        # degradation as degrade_unsupported, counted so reporting stays
        # honest about every persisted field the run clears.
        out.degraded.append(UNSUPPORTED_DEADLINE)
    # Over-broad area claims narrow to the curated field the source itself
    # declares; the record's own evidence vetoes narrowing when it names
    # other descendants (Q1 — NASW social_sciences/social_work finding).
    narrowed = narrow_disciplines_to_evidence(
        extract.eligible_disciplines, evidence, source_discipline)
    if narrowed != list(extract.eligible_disciplines or []):
        extract.eligible_disciplines = narrowed
    attach_verification(extract, text=evidence, source_url=source_url)

    # -- Degradation of unsupported optional claims -------------------------
    if extract.verification_status != "verified":
        verdicts = getattr(extract, "verified_fields", {}) or {}
        remaining, _ = _recompute_reasons(extract, evidence)
        degradable = [r for r in remaining if r in DEGRADABLE_REASONS]
        hard = [r for r in remaining if r not in DEGRADABLE_REASONS]
        # Degrade only when every remaining blocker is an optional claim —
        # a hard gate left standing keeps its evidence intact for review.
        if not hard and degradable:
            removed = degrade_unsupported(extract, verdicts, degradable)
            if removed:
                out.degraded.extend(r for r in removed
                                      if r not in out.degraded)
                attach_verification(extract, text=evidence, source_url=source_url)

    # -- Final interpretation -----------------------------------------------
    final_reasons, _ = _recompute_reasons(extract, evidence)
    if title_absent_on_source and UNSUPPORTED_TITLE in final_reasons:
        final_reasons[final_reasons.index(UNSUPPORTED_TITLE)] = TITLE_ABSENT_ON_SOURCE
    out.reasons_after = final_reasons

    if extract.verification_status == "verified":
        out.action = "verified"
        out.cleared = True
        out.queue = AUTO_RECHECK  # resolved by machine re-evaluation
        if not dry_run:
            _apply_outcome(row, extract)
        return out

    # Still gated — classify the residue.
    out.action = "gated"
    out.queue = HUMAN_REVIEW if any(r in PERMANENT_REASONS or r in (FUND_TITLE_EVIDENCE,)
                                    for r in final_reasons) else AUTO_RECHECK
    if out.queue == AUTO_RECHECK and out.degraded:
        # Degrading didn't clear it — a genuine residual blocker remains.
        out.queue = HUMAN_REVIEW
    return out


def _recompute_reasons(extract: ScholarshipExtract,
                       evidence: str) -> Tuple[List[str], List[str]]:
    """Reason list after evaluation, mirroring the ingest-time gates on the
    same evidence. Returns (reasons, evidence_checks)."""
    reasons: List[str] = []
    vf = getattr(extract, "verified_fields", {}) or {}
    for fname, verdict in vf.items():
        if fname in _FIELD_REASONS and verdict == "unverified":
            reasons.append(_FIELD_REASONS[fname])
    reasons.extend(structural_reasons(
        extract.title, extract.provider, extract.eligible_disciplines))
    if [str(d).lower() for d in extract.eligible_disciplines] == ["any"]:
        if not _ANY_FIELD_EVIDENCE.search(evidence or ""):
            reasons.append(UNSUPPORTED_ANY)
    if _FUND_ACCOUNT_TITLE.search(extract.title or ""):
        if not _EDU_FUNDING_TERM.search(evidence or ""):
            reasons.append(FUND_TITLE_EVIDENCE)
    if extract.title and not _title_on_evidence(extract.title, evidence):
        if UNSUPPORTED_TITLE not in reasons:
            reasons.append(UNSUPPORTED_TITLE)
    order = [
        UNSUPPORTED_TITLE, UNSUPPORTED_AWARD, UNSUPPORTED_DEADLINE,
        UNSUPPORTED_GPA, UNSUPPORTED_ANY, FUND_TITLE_EVIDENCE,
        NO_OPPORTUNITY_NOUN, GENERIC_PROVIDER, NO_PERSISTED_EVIDENCE,
        TITLE_ABSENT_ON_SOURCE, SOURCE_UNVERIFIABLE,
    ]
    reasons = list(dict.fromkeys(reasons))
    reasons.sort(key=lambda r: order.index(r) if r in order else len(order))
    return reasons, []


def _title_on_evidence(title: str, evidence: str) -> bool:
    from .extraction import title_on_page

    return title_on_page(title, evidence or "")


def _apply_outcome(row, extract: ScholarshipExtract) -> None:
    """Persist the clearance (called only inside a managed session)."""
    from app.services import lifecycle

    row.award_amount = extract.award_amount
    if getattr(row, "deadline", None) != (date.fromisoformat(extract.deadline)
                                        if extract.deadline else None):
        # Deadline cleared or corrected — its derived cycle estimate has no
        # remaining basis and is reset with it.
        row.deadline = date.fromisoformat(extract.deadline) if extract.deadline else None
        if extract.deadline is None:
            row.estimated_next_cycle = None
    row.min_gpa = extract.min_gpa if extract.min_gpa is not None else 0.0
    row.eligible_disciplines = list(extract.eligible_disciplines or [])
    row.is_general_major = bool(extract.is_general_major)
    row.verification_status = extract.verification_status
    row.verified_fields = dict(getattr(extract, "verified_fields", {}) or {})
    row.verified_at = getattr(extract, "verified_at", None) or datetime.utcnow()
    lifecycle.record_check(row)


# ---------------------------------------------------------------------------
# Backlog classification & queue (Phase 1 + Phase 4 — DB reads only)
# ---------------------------------------------------------------------------


def _source_health_map(db) -> Dict[str, str]:
    from app.models.models import CatalogSource

    return {
        url: health for url, health in
        db.query(CatalogSource.url, CatalogSource.health).all()
    }


def _source_discipline_map(db) -> Dict[str, str]:
    """source_url -> the registry's curated primary_discipline.

    ``'any'`` is not a canonical field code — sources that declare it
    propose no narrowing candidate, which is exactly what keeps genuinely
    broad programs (IHS LRP, Gilman STEM, ...) untouched.
    """
    from app.models.models import CatalogSource

    return {
        url: disc for url, disc in
        db.query(CatalogSource.url, CatalogSource.primary_discipline).all()
        if disc
    }


def classify_backlog(db, *, include_archived: bool = True) -> List[dict]:
    """Classify every persisted needs_review record (no fetches, no writes)."""
    from app.models.models import Scholarship

    rows = (db.query(Scholarship)
            .filter(Scholarship.verification_status == "needs_review")
            .all())
    health = _source_health_map(db)
    out = []
    for row in rows:
        reasons, checks = classify_record(row)
        src_health = health.get(getattr(row, "source_url", "") or "")
        cat = queue_category(row, reasons, checks, source_health=src_health)
        if not include_archived and cat == ARCHIVED_SKIP:
            continue
        out.append({
            "id": str(row.id),
            "title": row.title,
            "provider": row.provider,
            "source_url": row.source_url,
            "portal_url": row.portal_url,
            "lifecycle_status": row.lifecycle_status,
            "archive_reason": row.archive_reason,
            "source_health": src_health,
            "reasons": reasons,
            "evidence_checks": checks,
            "queue": cat,
            "single_blocker": len(reasons) + len(checks) == 1,
            "extraction_method": row.extraction_method,
            "last_checked_at": row.last_checked_at.isoformat()
            if getattr(row, "last_checked_at", None) else None,
            "verified_fields": _vf(row),
        })
    return out


def backlog_summary(classified: Sequence[dict]) -> dict:
    """Aggregate the classified backlog into the BEFORE distribution."""
    reason_counts: Counter = Counter()
    for c in classified:
        for r in c["reasons"]:
            reason_counts[r] += 1
        for chk in c.get("evidence_checks", []):
            reason_counts[chk] += 1
    queue_counts = Counter(c["queue"] for c in classified)
    single = sum(1 for c in classified if c["single_blocker"])
    return {
        "records": len(classified),
        "reason_distribution": dict(reason_counts.most_common()),
        "queue_distribution": dict(queue_counts.most_common()),
        "single_blocker": single,
        "multi_blocker": len(classified) - single,
    }


def review_queue(db) -> Dict[str, List[dict]]:
    """Programmatic review queue — derived on demand, nothing persisted.

    A later admin interface consumes this directly: each entry carries the
    record's identity, links, reasons, source health, and last check."""
    grouped: Dict[str, List[dict]] = {
        c: [] for c in (*QUEUE_CATEGORIES, ARCHIVED_SKIP, ARCHIVED_EXCLUDED)}
    for entry in classify_backlog(db):
        grouped[entry["queue"]].append(entry)
    return grouped


# ---------------------------------------------------------------------------
# Clearance run (Phase 5) — bounded, staged, local DB only
# ---------------------------------------------------------------------------


def _snapshot(db) -> dict:
    from app.models.models import Scholarship

    rows = db.query(
        Scholarship.verification_status, Scholarship.lifecycle_status).all()
    ver = Counter(v for v, _ in rows)
    life = Counter(l for _, l in rows)
    return {
        "total": len(rows),
        "verification": dict(ver),
        "lifecycle": dict(life),
        "discoverable": sum(
            1 for v, l in rows
            if l == "published" and v != "needs_review"),
    }


async def run_clearance(
    db,
    *,
    limits: Optional[ReviewLimits] = None,
    include_archived: bool = False,
    dry_run: bool = False,
    limit: Optional[int] = None,
    session: Optional[FetchSession] = None,
) -> dict:
    """Stage the whole needs_review backlog through re-evaluation.

    Stages: deterministic recheck on the stored source listing -> bounded
    authoritative detail fetch -> safe optional-claim degradation ->
    leave genuine human cases gated. Archived deadline_passed records are
    classified but not worked unless ``include_archived`` (an explicit
    current-cycle review); records archived for a sticky reason
    (duplicate/manual/discontinued/source_removed) are never worked.
    """
    from app.models.models import Scholarship

    limits = limits or ReviewLimits.from_env()
    session = session or default_session()
    classified = [c for c in classify_backlog(db)
                  if c["queue"] != ARCHIVED_EXCLUDED
                  and (include_archived or c["queue"] != ARCHIVED_SKIP)]
    if limit:
        classified = classified[:limit]

    # Group by source page: siblings share one fetch and rebuild each other's
    # evidence windows — bounded fan-out identical to extraction.
    by_source: Dict[str, List[dict]] = {}
    for c in classified:
        by_source.setdefault(c["source_url"] or "", []).append(c)

    # Evidence windows need EVERY persisted title on a source page — verified
    # siblings included — or a gated record's segment could bleed into a
    # sibling's facts and falsely verify them (C5 isolation rule).
    source_titles: Dict[str, List[str]] = {}
    for src_url, title in db.query(Scholarship.source_url, Scholarship.title).all():
        source_titles.setdefault(src_url or "", []).append(title or "")

    pages_fetched = 0
    page_cache: Dict[str, FetchResult] = {}

    async def _fetch(url: str) -> FetchResult:
        nonlocal pages_fetched
        if url in page_cache:
            return page_cache[url]
        if pages_fetched >= limits.max_pages_fetched:
            res = FetchResult(url=url, outcome="run_cap", error="Q1 page cap reached")
            page_cache[url] = res
            return res
        res = await session.get(url, timeout=limits.fetch_timeout)
        pages_fetched += 1
        page_cache[url] = res
        return res

    id_index = {c["id"]: c for c in classified}
    src_disciplines = _source_discipline_map(db)
    results: Dict[str, ReviewOutcome] = {}
    counts = Counter()

    for source_url, group in by_source.items():
        sibling_titles = source_titles.get(source_url, [g["title"] for g in group])
        for c in group:
            row = db.query(Scholarship).filter(Scholarship.id == c["id"]).first()
            if row is None:
                continue
            outcome = await reevaluate_record(
                row, fetch=_fetch, sibling_titles=sibling_titles,
                source_discipline=src_disciplines.get(source_url or ""),
                dry_run=dry_run)
            results[c["id"]] = outcome
            counts[outcome.action] += 1
            if not dry_run:
                try:
                    db.commit()
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    logger.error("Commit failed for %s: %s", c["id"], exc)
                    counts["commit_error"] += 1

    return {
        "classified": len(classified),
        "worked": counts.get("verified", 0) + counts.get("gated", 0)
        + counts.get("blocked", 0) + counts.get("skipped", 0),
        "cleared": counts.get("verified", 0),
        "still_gated": counts.get("gated", 0),
        "blocked": counts.get("blocked", 0),
        "skipped": counts.get("skipped", 0),
        "commit_errors": counts.get("commit_error", 0),
        "pages_fetched": pages_fetched,
        "llm_calls": 0,
        "degradations": sum(len(o.degraded) for o in results.values()),
        "outcomes": {
            rid: {
                "action": o.action, "cleared": o.cleared, "degraded": o.degraded,
                "reasons_before": o.reasons_before, "reasons_after": o.reasons_after,
                "queue": o.queue, "evidence_urls": o.evidence_urls,
                "fetch_outcomes": o.fetch_outcomes,
            }
            for rid, o in results.items()
        },
        "dry_run": dry_run,
    }


# ---------------------------------------------------------------------------
# Discipline over-breadth reclaim (NASW finding — provider-agnostic)
# ---------------------------------------------------------------------------


async def reclaim_discipline_overbreadth(
    db,
    *,
    limits: Optional[ReviewLimits] = None,
    dry_run: bool = False,
    session: Optional[FetchSession] = None,
) -> dict:
    """Narrow persisted area-level discipline claims to each source's curated
    field, gated by the record's own authoritative evidence.

    Records with a broad area code (e.g. ``social_sciences``) narrow to the
    more specific canonical field the *source registry itself declares*
    (``catalog_sources.primary_discipline``) — provided the record's own
    evidence does not name other descendants of that area. Verified records
    keep their status; only the discipline claim changes, and only through
    this curated-declaration + evidence-veto rule (never page-text matching
    alone — a partial matcher cannot safely cover genuinely broad programs).
    """
    from app.models.models import Scholarship
    from app.services import lifecycle
    from .utils.taxonomy import _AREA_CHILDREN

    limits = limits or ReviewLimits.from_env()
    session = session or default_session()
    areas = list(_AREA_CHILDREN)
    rows = (db.query(Scholarship)
            .filter(Scholarship.eligible_disciplines.overlap(areas))
            .all())

    source_titles: Dict[str, List[str]] = {}
    for src_url, title in db.query(Scholarship.source_url, Scholarship.title).all():
        source_titles.setdefault(src_url or "", []).append(title or "")
    src_disciplines = _source_discipline_map(db)

    pages_fetched = 0
    cache: Dict[str, FetchResult] = {}
    examined = narrowed_count = blocked = 0
    changed: List[dict] = []

    for row in rows:
        url = row.source_url or row.portal_url or ""
        if not url:
            continue
        if url not in cache:
            if pages_fetched >= limits.max_pages_fetched:
                break
            cache[url] = await session.get(url, timeout=limits.fetch_timeout)
            pages_fetched += 1
        res = cache[url]
        if not (res.ok and res.text):
            blocked += 1
            continue
        text = html_to_text(res.text)
        sibs = [t for t in source_titles.get(row.source_url or "", [])
                if t and t != row.title]
        evidence = (evidence_windows(text, [row.title, *sibs])[0]
                    if sibs else text)
        narrowed = narrow_disciplines_to_evidence(
            row.eligible_disciplines, evidence,
            src_disciplines.get(row.source_url or ""))
        examined += 1
        if narrowed != list(row.eligible_disciplines or []):
            before = list(row.eligible_disciplines or [])
            if not dry_run:
                row.eligible_disciplines = narrowed
                lifecycle.record_check(row)
                db.commit()
            narrowed_count += 1
            changed.append({
                "id": str(row.id), "title": row.title,
                "provider": row.provider,
                "before": before, "after": narrowed,
            })

    return {
        "records_with_area_claims": len(rows),
        "examined": examined,
        "narrowed": narrowed_count,
        "blocked": blocked,
        "pages_fetched": pages_fetched,
        "changes": changed,
        "dry_run": dry_run,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: Optional[List[str]] = None) -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        prog="scrapers.review",
        description="Q1 catalog review & clearance engine (backend only)",
    )
    parser.add_argument("--classify", action="store_true",
                        help="print the needs_review forensic distribution")
    parser.add_argument("--queue", action="store_true",
                        help="print the derived review queue")
    parser.add_argument("--run", action="store_true",
                        help="run bounded re-evaluation against the backlog")
    parser.add_argument("--reclaim-disciplines", action="store_true",
                        help="narrow over-broad area discipline claims on evidence")
    parser.add_argument("--dry-run", action="store_true",
                        help="evaluate without writing")
    parser.add_argument("--include-archived", action="store_true",
                        help="explicit current-cycle review: also work deadline_passed "
                             "archived records (duplicate/manual/discontinued/"
                             "source_removed are never worked)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--snapshot", action="store_true",
                        help="print catalog snapshot only")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        if args.snapshot:
            print(json.dumps(_snapshot(db), indent=2, default=str))

        if args.classify:
            classified = classify_backlog(db)
            print(json.dumps(backlog_summary(classified), indent=2, default=str))

        if args.queue:
            queue = review_queue(db)
            print(json.dumps(
                {k: len(v) for k, v in queue.items()}, indent=2))
            for cat, entries in queue.items():
                for e in entries[:10]:
                    print(f"[{cat}] {e['title'][:70]} | {e['provider'][:40]} | "
                          f"{','.join(e['reasons'] + e['evidence_checks'])}")

        if args.reclaim_disciplines:
            out = asyncio.run(reclaim_discipline_overbreadth(
                db, dry_run=args.dry_run))
            print(json.dumps(out, indent=2, default=str))

        if args.run:
            summary = asyncio.run(run_clearance(
                db, include_archived=args.include_archived,
                dry_run=args.dry_run, limit=args.limit))
            after = _snapshot(db)
            summary["after"] = after
            print(json.dumps({k: v for k, v in summary.items() if k != "outcomes"},
                             indent=2, default=str))
            out_path = os.getenv("Q1_REPORT_PATH", "q1_clearance_report.json")
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(summary, fh, indent=2, default=str)
            logger.info("Per-record outcomes written to %s", out_path)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
