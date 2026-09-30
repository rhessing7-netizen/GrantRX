"""CLI runner, dedup upsert, auto-archival, and daily AsyncIO scheduler.

Three-tier scraper pipeline:
  Tier 1 — Deterministic: httpx + BeautifulSoup parsers for structured pages.
  Tier 2 — Playwright: headless browser for JS-rendered SPAs.
  Tier 3 — LLM Fallback: instructor + OpenAI/LiteLLM for unstructured content.

Usage:
    python -m scrapers.runner --target=all
    python -m scrapers.runner --target=https://www.pharmacist.com/...
    python -m scrapers.runner --target=all --dry-run
    python -m scrapers.runner --category=regional_foundation
    python -m scrapers.runner --category=corporate_unrestricted --limit=3
    python -m scrapers.runner --state=CA
    python -m scrapers.runner --schedule   # run daily at 03:00 local time
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from .extraction import (
    PAGE_IRRELEVANT,
    ExtractionStats,
    PageExtraction,
    attach_verification,
    extract_page,
)
from .fetch_policy import (
    INCONCLUSIVE_OUTCOMES,
    FetchResult,
    default_session,
)
from .fetcher import fetch_many
from .verification import html_to_text
from .schema import ScholarshipExtract
from .sources import SourceConfig, load_sources
from .utils.identity import (
    canonical_identity_url,
    compute_identity_keys,
    normalize_identity_text,
    same_identity,
)
from .utils.normalize import add_one_year, parse_date
from .utils.url_safety import is_safe_replacement_url, is_specific_opportunity_url

logger = logging.getLogger("scrapers.runner")

# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def _resolve_portal_url(extracted_url: str, source_url: str) -> str:
    """Resolve a potentially relative portal URL to an absolute URL.

    If the extracted URL is relative (e.g. '/apply'), join it with the source URL.
    If it's already absolute, return as-is. If empty, fall back to the source URL.
    """
    if not extracted_url or not extracted_url.strip():
        return source_url
    extracted_url = extracted_url.strip()
    parsed = urlparse(extracted_url)
    if parsed.scheme in ("http", "https"):
        return extracted_url
    # Relative URL — resolve against the source URL
    return urljoin(source_url, extracted_url)


async def _check_url_result(url: str, *, timeout: float = 5.0) -> FetchResult:
    """Outcome-aware HEAD/GET check through the C6 fetch policy.

    Robots.txt, per-host pacing, and bounded retries are applied by the
    shared session. The returned FetchResult distinguishes a definitive
    HTTP response from inconclusive outcomes (robots denial, timeout,
    network error) — callers must not treat "we couldn't check" as "dead".
    """
    try:
        return await default_session().check(url, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return FetchResult(url=url, outcome="network_error",
                           error=f"{type(exc).__name__}"[:200])


async def _verify_url(url: str, *, timeout: float = 5.0) -> bool:
    """Verify a URL returns HTTP < 400 (compat wrapper).

    True only on a definitive successful response. False on errors and on
    inconclusive outcomes — callers that need to tell those apart should
    use ``_check_url_result`` directly.
    """
    result = await _check_url_result(url, timeout=timeout)
    return bool(result.ok and (result.http_status is None or result.http_status < 400))


async def _verify_portal_url(
    portal_url: str,
    source_url: str,
) -> Tuple[str, bool, bool]:
    """Verify the portal URL, falling back to source URL if needed.

    Returns (final_url, is_valid, decisive). ``decisive`` is False when the
    check never got a definitive answer (robots denial, timeout, network
    error): the caller must not drop the opportunity or mark its
    destination verified on an inconclusive check. ``is_valid`` False with
    ``decisive`` True means a real HTTP >= 400 — a dead link.
    """
    # Resolve relative paths against the source URL
    resolved_url = _resolve_portal_url(portal_url, source_url)

    result = await _check_url_result(resolved_url)
    if result.outcome in INCONCLUSIVE_OUTCOMES:
        logger.info("Portal URL check inconclusive (%s): %s — keeping record",
                    result.outcome, resolved_url)
        return resolved_url, True, False
    if result.ok and result.http_status is not None and result.http_status < 400:
        return resolved_url, True, True

    # Portal URL is dead. The source URL may stand in only if it is itself an
    # opportunity-specific page on the same site (shared rule with the
    # dead-link repair job). A generic homepage or unrelated page is never an
    # acceptable replacement — the entry is dropped instead.
    if resolved_url != source_url and not is_safe_replacement_url(source_url, [resolved_url]):
        logger.warning(
            "Portal URL dead (%s) and source URL is not a safe opportunity-specific "
            "replacement (%s) — link will not be saved",
            resolved_url, source_url,
        )
        return resolved_url, False, True

    logger.warning(
        "Portal URL returned HTTP %s: %s — checking source URL fallback",
        result.http_status, resolved_url,
    )
    if resolved_url != source_url:
        src_result = await _check_url_result(source_url)
        if src_result.outcome in INCONCLUSIVE_OUTCOMES:
            return source_url, True, False
        if src_result.ok and src_result.http_status is not None and src_result.http_status < 400:
            return source_url, True, True

    # Both are dead — caller should drop the entry and increment dead_links
    logger.warning(
        "Source URL also unreachable: %s — link will not be saved",
        source_url,
    )
    return resolved_url, False, True


# ---------------------------------------------------------------------------
# Result reporting
# ---------------------------------------------------------------------------


@dataclass
class ScrapeResult:
    """Outcome of extracting one source page (zero, one, or many opportunities)."""

    url: str
    status: str  # "ok" | "llm_fallback" | "irrelevant" | "empty" | "error"
    extracts: List[ScholarshipExtract] = field(default_factory=list)
    error: Optional[str] = None
    page: Optional[PageExtraction] = None

    @property
    def extract(self) -> Optional[ScholarshipExtract]:
        """First opportunity (single-record compatibility accessor)."""
        return self.extracts[0] if self.extracts else None

    @property
    def is_multi(self) -> bool:
        return bool(self.page and self.page.is_multi)


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


def _detail_fetcher(scraper_type: str = "deterministic"):
    """Bounded listing -> detail fetch using the shared fetch infrastructure."""
    from .fetcher import fetch_html

    async def _fetch(u: str) -> Optional[str]:
        return await fetch_html(u, scraper_type=scraper_type)

    return _fetch


def _page_to_result(page: PageExtraction) -> ScrapeResult:
    if page.kind == PAGE_IRRELEVANT:
        status = "irrelevant"
    elif page.error:
        status = "error"
    elif not page.extracts:
        status = "empty"
    else:
        status = "ok" if page.method == "deterministic" else "llm_fallback"
    return ScrapeResult(url=page.url, status=status, extracts=list(page.extracts),
                        error=page.error, page=page)


def _apply_source_metadata(extracts: List[ScholarshipExtract], src: SourceConfig, *, multi: bool) -> None:
    """Attach curated source metadata to each extracted opportunity.

    Curated eligibility hints (state / discipline / credentials) were authored
    under the one-opportunity-per-page assumption. On a multi-opportunity page
    they are NOT copied onto every child — a page-wide restriction must be
    explicitly stated on the page (C5 rule 4).
    """
    for ex in extracts:
        ex.source_name = src.name
        ex.source_category = src.category
        if not ex.provider:
            ex.provider = src.name
        if multi:
            continue
        if src.state_restriction and not ex.state_restrictions:
            ex.state_restrictions = [src.state_restriction]
            # A configured state restriction IS established geography — the
            # scope may now be stated ('state'), though never 'national' by
            # default.
            if not ex.scope:
                ex.scope = "state"
        if src.primary_discipline != "any" and not ex.eligible_disciplines:
            ex.eligible_disciplines = [src.primary_discipline]
        if src.target_credentials and not ex.eligible_credentials:
            ex.eligible_credentials = src.target_credentials


async def scrape_url(
    url: str,
    provider_hint: str = "",
    scraper_type: str = "deterministic",
) -> ScrapeResult:
    """Fetch + extract a single URL (zero, one, or many opportunities)."""
    from .fetcher import fetch_html

    try:
        html = await fetch_html(url, scraper_type=scraper_type)
    except Exception as exc:  # noqa: BLE001
        logger.error("Fetch failed for %s: %s", url, exc)
        return ScrapeResult(url=url, status="error", error=str(exc))

    if not html:
        return ScrapeResult(url=url, status="error", error="empty response")

    page = await extract_page(html, url, provider_hint=provider_hint,
                              fetch_detail=_detail_fetcher(scraper_type))
    return _page_to_result(page)


async def scrape_many(
    sources: List[SourceConfig],
    *,
    concurrency: int = 5,
    stats: Optional[ExtractionStats] = None,
) -> List[ScrapeResult]:
    """Fetch all sources concurrently, then extract sequentially (DB-safe).

    Error isolation: if one URL times out or fails parsing, the error is logged
    and the batch continues to the next source.
    """
    urls = [s.url for s in sources]
    scraper_types = {s.url: s.scraper_type for s in sources}

    # Fetch all URLs concurrently with tier-appropriate strategies
    fetched = await fetch_many(urls, concurrency=concurrency, scraper_types=scraper_types)

    # Build a url -> html map
    html_map: dict[str, Optional[str]] = {}
    for fetched_url, html in fetched:
        html_map[fetched_url] = html

    results: List[ScrapeResult] = []
    for src in sources:
        url = src.url
        html = html_map.get(url)

        if html is None:
            # Surface the policy outcome (robots_denied, timeout, HTTP 404)
            # instead of a bare "fetch failed" when the session recorded one.
            last = default_session().last_results.get(url)
            detail = last.outcome if last is not None else "fetch failed"
            if last is not None and last.http_status:
                detail = f"{detail} (HTTP {last.http_status})"
            results.append(ScrapeResult(url=url, status="error", error=detail))
            logger.error("Fetch %s for %s (source: %s)", detail, url, src.name)
            continue

        if not html:
            results.append(ScrapeResult(url=url, status="error", error="empty response"))
            logger.error("Empty HTML for %s (source: %s)", url, src.name)
            continue

        try:
            page = await extract_page(html, url, provider_hint=src.name,
                                      fetch_detail=_detail_fetcher(src.scraper_type))
        except Exception as exc:  # noqa: BLE001
            logger.error("Extraction crashed for %s: %s — continuing", url, exc)
            results.append(ScrapeResult(url=url, status="error", error=f"extraction crashed: {exc}"[:300]))
            continue
        if stats is not None:
            stats.add(page)
        _apply_source_metadata(page.extracts, src, multi=page.is_multi)
        logger.info("[%s] %s -> %d opportunity(ies), %d rejected",
                    page.kind, url, len(page.extracts), len(page.rejected))
        results.append(_page_to_result(page))

    return results


# ---------------------------------------------------------------------------
# Database upsert + auto-archival
# ---------------------------------------------------------------------------


def _coerce_deadline(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    d = parse_date(value)
    return d


def _attach_source_verification(extract: ScholarshipExtract, html: str, source_url: str) -> ScholarshipExtract:
    """Attach non-LLM field evidence (whole page) before an extract can be persisted."""
    return attach_verification(extract, text=html_to_text(html), source_url=source_url)


def _to_db_dict(extract: ScholarshipExtract) -> dict:
    """Map a ScholarshipExtract to a dict suitable for SQLAlchemy model kwargs.

    Lifecycle fields (lifecycle_status, archive_reason, is_archived,
    last_seen_at, ...) are deliberately absent: they are owned by
    ``app.services.lifecycle`` and applied by ``upsert_scholarship``, so a
    generic field refresh can never silently resurrect an archived record.
    """
    deadline = _coerce_deadline(extract.deadline)
    today = date.today()
    # A missing/rolling/not-yet-announced deadline is not an expired deadline.
    deadline_past = bool(deadline and deadline < today)
    estimated_next_cycle = add_one_year(deadline) if deadline_past else (
        parse_date(extract.estimated_next_cycle) if extract.estimated_next_cycle else None
    )

    return {
        "title": extract.title,
        "provider": extract.provider,
        "portal_url": extract.portal_url,
        # Funding awards are never zero/negative; nonpositive extraction
        # output means "unknown" and must persist as NULL.
        "award_amount": extract.award_amount if extract.award_amount and extract.award_amount > 0 else None,
        "deadline": deadline,
        "eligible_disciplines": _canonical_disciplines(extract.eligible_disciplines),
        "eligible_credentials": extract.eligible_credentials or [],
        "min_gpa": extract.min_gpa if extract.min_gpa is not None else 0.0,
        "max_sai": extract.max_sai,
        "state_restrictions": extract.state_restrictions or [],
        "metro_restrictions": extract.metro_restrictions or [],
        "required_affiliations": extract.required_affiliations or [],
        "matching_tags": extract.matching_tags or [],
        "estimated_next_cycle": estimated_next_cycle,
        # Academic criteria — general major & academic levels
        "is_general_major": getattr(extract, "is_general_major", False),
        "academic_levels": getattr(extract, "academic_levels", []) or [],
        # Geographic targeting — NULL means "never established"; an explicit
        # unrestricted award stores 'national'. Unknown must not persist as
        # national (C8 / C6.5 calibration finding).
        "scope": getattr(extract, "scope", None) or None,
        "county_restrictions": getattr(extract, "county_restrictions", []) or [],
        "city_restrictions": getattr(extract, "city_restrictions", []) or [],
        # Provider alignment & local discovery
        "provider_type": extract.provider_type,
        "provider_mission": extract.provider_mission,
        "provider_core_values": extract.provider_core_values or [],
        "is_local": extract.is_local,
        "competition_level": getattr(extract, "competition_level", "medium") or "medium",
        "target_community": extract.target_community,
        # Employer tuition assistance, service-obligation, and vendor-platform fields
        "funding_type": getattr(extract, "funding_type", None) or None,
        "employment_required": bool(getattr(extract, "employment_required", False)),
        "min_employment_tenure_months": getattr(extract, "min_employment_tenure_months", None),
        "annual_benefit_cap": getattr(extract, "annual_benefit_cap", None),
        "benefit_coverage_model": getattr(extract, "benefit_coverage_model", None),
        "partner_network": getattr(extract, "partner_network", None),
        "has_service_commitment": bool(getattr(extract, "has_service_commitment", False)),
        "service_commitment_duration_months": getattr(extract, "service_commitment_duration_months", None),
        "vendor_platform": getattr(extract, "vendor_platform", None),
        # C8 eligibility dimensions — all record-only until profiles collect
        # matching attributes; persisted verbatim, never inferred.
        "citizenship_requirement": getattr(extract, "citizenship_requirement", None),
        "enrollment_statuses": getattr(extract, "enrollment_statuses", []) or [],
        "institution_restrictions": getattr(extract, "institution_restrictions", []) or [],
        "military_affiliation_requirement": getattr(extract, "military_affiliation_requirement", None),
        "source_url": getattr(extract, "source_url", None),
        "extraction_method": getattr(extract, "source", None),
        "verification_status": getattr(extract, "verification_status", "legacy_unverified"),
        "verified_fields": getattr(extract, "verified_fields", {}) or {},
        "verified_at": getattr(extract, "verified_at", None),
        "updated_at": datetime.utcnow(),
    }


# Backwards-compatible aliases — the canonical implementation of opportunity
# identity lives in scrapers.utils.identity (Catalog Batch C4).
_canonical_identity_url = canonical_identity_url
_normalize_identity_text = normalize_identity_text


def _same_scholarship_identity(existing, extract) -> bool:
    """Conservatively decide whether an existing row is the same opportunity."""
    return same_identity(
        existing,
        title=extract.title, provider=extract.provider,
        portal_url=extract.portal_url, source_url=getattr(extract, "source_url", None),
    )


def _find_by_identity(db, model, identity_key, fallback_key, probe_fields):
    """Indexed identity lookup — replaces the pre-C4 full-table scan.

    Precedence: exact ``identity_key`` hit; then the title+provider fallback
    (``identity_fallback_key``, or a legacy row whose primary key IS the tp
    key); then a bounded compatibility scan over rows that predate the
    identity backfill (``identity_key IS NULL``).
    """
    from sqlalchemy import or_

    if identity_key:
        rows = db.query(model).filter(model.identity_key == identity_key).all()
        if rows:
            return rows[0]
    # The title+provider claim must be searched in BOTH columns even when it
    # is the incoming record's primary key: a stored row may hold it in
    # identity_fallback_key under a URL identity.
    tp_key = fallback_key
    if not tp_key and identity_key and identity_key.startswith("tp:"):
        tp_key = identity_key
    if tp_key:
        rows = (
            db.query(model)
            .filter(or_(
                model.identity_key == tp_key,
                model.identity_fallback_key == tp_key,
            ))
            .all()
        )
        if rows:
            # Deterministic choice when a pre-existing duplicate pair matches.
            rows.sort(key=lambda r: (r.created_at is None, r.created_at))
            return rows[0]
    # Bounded legacy-compat scan: only rows the backfill has not reached.
    for candidate in db.query(model).filter(model.identity_key.is_(None)).all():
        if same_identity(candidate, **probe_fields):
            return candidate
    return None


def _canonical_disciplines(values) -> list:
    """Persist canonical field-of-study codes only (C8).

    'any' is preserved (explicit unrestricted); unrecognized strings are
    dropped — a guessed discipline silently hard-gates users.
    """
    from .utils.taxonomy import ANY_FIELD, normalize_field_of_study

    out = []
    for v in values or []:
        canon = normalize_field_of_study(str(v))
        if canon and canon not in out:
            out.append(canon)
    if ANY_FIELD in out:
        return [ANY_FIELD]
    return out


def _sync_tracks(db, scholarship, extract) -> int:
    """Persist a parent's named tracks (C8).

    Replace-on-extract semantics only when the extract actually carries
    tracks — an extract with no tracks leaves existing rows untouched so a
    transient empty output can't wipe known program structure. Tracks never
    get their own identity keys; they live under the parent's identity.
    """
    from app.models.models import ScholarshipTrack

    tracks = getattr(extract, "tracks", None)
    if not tracks:
        return 0
    encoding = _db_encoding(db)
    db.query(ScholarshipTrack).filter(ScholarshipTrack.scholarship_id == scholarship.id).delete()
    count = 0
    for i, t in enumerate(tracks):
        deadline = _coerce_deadline(t.deadline)
        db.add(ScholarshipTrack(
            scholarship_id=scholarship.id,
            title=_db_safe_text(t.title, encoding),
            detail_url=_db_safe_text(t.detail_url, encoding),
            award_amount=t.award_amount if t.award_amount and t.award_amount > 0 else None,
            deadline=deadline,
            eligible_disciplines=_canonical_disciplines(t.eligible_disciplines) or None,
            eligible_credentials=[str(c) for c in (t.eligible_credentials or [])] or None,
            sort_order=i,
        ))
        count += 1
    return count


def _db_encoding(db) -> str:
    """Best-effort client encoding of the bound DB connection.

    psycopg encodes bound strings with the connection encoding, so a
    WIN1252 local dev database (Windows initdb default) cannot store
    characters outside cp1252 — e.g. the Hawaiian ʻokina. UTF-8
    connections accept everything and short-circuit the sanitizer."""
    try:
        raw = db.connection()
        # Walk SQLAlchemy Connection -> pool fairy -> DBAPI driver conn.
        conn = getattr(raw, "driver_connection", None) or raw
        conn = getattr(getattr(conn, "connection", None), "driver_connection", conn)
        enc = getattr(getattr(conn, "info", None), "encoding", None)
        if isinstance(enc, str) and enc:
            import codecs
            try:
                return codecs.lookup(enc).name
            except LookupError:
                pass
        return "utf-8"
    except Exception:  # noqa: BLE001
        return "utf-8"


def _db_safe_text(value, encoding: str):
    """Coerce a string to one the bound connection can encode.

    Characters outside the connection encoding (e.g. U+02BB under
    WIN1252) would otherwise raise UnicodeEncodeError mid-INSERT and
    silently drop the whole record after the source was already marked
    extracted. Only the unencodable characters themselves are replaced —
    everything the encoding CAN store (½, ™, ², é …) is left byte-for-byte
    untouched: modifier-letter punctuation maps to an apostrophe
    (ʻ -> '), others to their NFKC compatibility form when that form is
    encodable, and anything still unrepresentable is dropped (logged)."""
    if not isinstance(value, str):
        if isinstance(value, (list, tuple)):
            return [_db_safe_text(v, encoding) for v in value]
        return value
    try:
        value.encode(encoding)
        return value
    except UnicodeEncodeError:
        pass
    except LookupError:
        return value
    import unicodedata

    out, dropped = [], 0
    for ch in value:
        try:
            ch.encode(encoding)
            out.append(ch)
            continue
        except UnicodeEncodeError:
            pass
        if ch in ("ʻ", "ʼ", "ʹ", "′"):
            out.append("'")
            continue
        compat = unicodedata.normalize("NFKC", ch)
        try:
            compat.encode(encoding)
            out.append(compat)
        except UnicodeEncodeError:
            dropped += 1
    if dropped:
        logger.warning("Dropped %d character(s) not storable in DB encoding %s: %r",
                       dropped, encoding, value[:80])
    return "".join(out)


def upsert_scholarship(
    db,
    extract: ScholarshipExtract,
    *,
    destination_verified: bool = False,
) -> Tuple[object, str]:
    """Create or update an opportunity via persisted indexed identity (C4).

    Identity lookup is an indexed query on ``identity_key`` (canonical
    opportunity-specific URL) with the ``tp:`` title+provider key as the
    conservative fallback — no full-table scan. The unique constraint on
    ``identity_key``/``identity_fallback_key`` is the database boundary: a
    concurrent insert of the same identity raises IntegrityError, which is
    recovered by re-looking-up and updating the winning row.

    Lifecycle transitions are delegated to ``app.services.lifecycle``:
    ``destination_verified`` remains the evidence required to reverse a
    ``dead_link`` archive.

    action is one of: "created", "updated".
    """
    from sqlalchemy.exc import IntegrityError

    from app.models.models import Scholarship  # local import to avoid import cycles
    from app.services import lifecycle

    data = _to_db_dict(extract)
    encoding = _db_encoding(db)
    if encoding not in ("utf-8", "utf8", "unicode"):
        data = {k: _db_safe_text(v, encoding) for k, v in data.items()}
    identity_key, fallback_key = compute_identity_keys(
        data["title"], data["provider"], data["portal_url"], data.get("source_url"),
    )
    if not identity_key:
        raise ValueError(
            f"cannot compute a stable opportunity identity for {extract.title!r}"
        )

    probe_fields = dict(
        title=data["title"], provider=data["provider"],
        portal_url=data["portal_url"], source_url=data.get("source_url"),
    )

    existing = _find_by_identity(db, Scholarship, identity_key, fallback_key, probe_fields)

    if existing is None:
        scholarship = Scholarship(
            created_at=datetime.utcnow(),
            identity_key=identity_key,
            identity_fallback_key=fallback_key,
            **data,
        )
        lifecycle.initialize_new(scholarship)
        db.add(scholarship)
        try:
            db.commit()
        except IntegrityError:
            # Unique-race: a concurrent ingestion already created this
            # identity. Re-locate the winning row and update it instead —
            # the unique constraint stays the authority.
            db.rollback()
            existing = _find_by_identity(db, Scholarship, identity_key, fallback_key, probe_fields)
            if existing is None:
                raise
        else:
            db.refresh(scholarship)
            if _sync_tracks(db, scholarship, extract):
                db.commit()
                db.refresh(scholarship)
            return scholarship, "created"

    for key, value in data.items():
        if getattr(existing, key) != value:
            setattr(existing, key, value)
    # Absorb identity changes: a row found via fallback had a provider URL
    # migration, so the new canonical URL becomes its primary identity.
    if getattr(existing, "identity_key", None) != identity_key:
        existing.identity_key = identity_key
    if getattr(existing, "identity_fallback_key", None) != fallback_key:
        existing.identity_fallback_key = fallback_key
    # A refresh is always an observation (last_seen_at advances), so the
    # record is always persisted. "unchanged" remains in the documented
    # return contract for callers but is no longer produced.
    lifecycle.apply_refresh(existing, destination_verified=destination_verified)
    _sync_tracks(db, existing, extract)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent row claimed this identity between lookup and commit —
        # that row is the identity's canonical holder; update it instead.
        db.rollback()
        owner = _find_by_identity(db, Scholarship, identity_key, fallback_key, probe_fields)
        if owner is None:
            raise
        for key, value in data.items():
            if getattr(owner, key) != value:
                setattr(owner, key, value)
        lifecycle.apply_refresh(owner, destination_verified=destination_verified)
        _sync_tracks(db, owner, extract)
        db.commit()
        db.refresh(owner)
        return owner, "updated"
    db.refresh(existing)
    return existing, "updated"


async def _persist_extract(db, extract: ScholarshipExtract, page_url: str, *, multi: bool) -> str:
    """Link-check and upsert ONE opportunity. Returns "created" | "updated" |
    "dead_link" | "error". Failures are isolated to this opportunity."""
    if not extract.is_critical_complete():
        return "error"
    destination_verified = False
    try:
        final_url, is_valid, decisive = await _verify_portal_url(extract.portal_url, page_url)
        if decisive and not is_valid:
            logger.warning("Skipping %s: portal_url dead and no safe opportunity-specific fallback",
                           extract.title)
            return "dead_link"
        # Resolution is deterministic — apply it even when the check itself
        # was inconclusive (robots denial, timeout). destination_verified is
        # only set on a DECISIVE live response: "we couldn't check" is not
        # evidence that the destination is live.
        extract.portal_url = final_url
        if decisive:
            # A listing URL is where a child was found, not evidence that the
            # child's own destination is live — it cannot reverse a dead_link.
            is_listing_url = multi and canonical_identity_url(final_url) == canonical_identity_url(page_url)
            destination_verified = is_specific_opportunity_url(final_url) and not is_listing_url
    except Exception as exc:  # noqa: BLE001
        logger.debug("Link verification failed for %s: %s — proceeding with save", extract.portal_url, exc)
    try:
        _, action = upsert_scholarship(db, extract, destination_verified=destination_verified)
        return action
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.error("Upsert failed for %s (%s): %s", page_url, extract.title, exc)
        return "error"


def archive_expired(db) -> int:
    """Archive expired scholarships via the single authoritative service.

    Kept as a thin compatibility wrapper for scraper CLI call sites.  The
    lifecycle rule itself lives in ``app.services.archiver`` so scheduled,
    admin, and scraper-triggered archival cannot drift apart.
    """
    from app.services.archiver import archive_expired_scholarships

    return archive_expired_scholarships(db)


# ---------------------------------------------------------------------------
# Source resolution & filtering
# ---------------------------------------------------------------------------


def _resolve_sources(
    target: str,
    *,
    category: Optional[str] = None,
    state: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[SourceConfig]:
    """Resolve sources from JSON/defaults, with optional filtering.

    Args:
        target: "all" or a specific URL.
        category: Filter by source category (e.g. "regional_foundation").
        state: Filter by 2-letter state code (regional sources only).
        limit: Max number of sources to process.
    """
    if target != "all":
        # Single URL — create a minimal SourceConfig
        host = urlparse(target).netloc
        hint = host.replace("www.", "").split(".")[0].title() if host else ""
        return [SourceConfig(name=hint, url=target, scraper_type="deterministic")]

    # Load all sources (from sources.json or Python defaults)
    all_sources = load_sources()

    # Filter by category
    if category:
        all_sources = [s for s in all_sources if s.category == category]
        logger.info("Filtered by category='%s': %d source(s)", category, len(all_sources))

    # Filter by state
    if state:
        state_upper = state.upper()
        all_sources = [s for s in all_sources if s.state_restriction == state_upper]
        logger.info("Filtered by state='%s': %d source(s)", state_upper, len(all_sources))

    # Apply limit
    if limit is not None and limit > 0:
        all_sources = all_sources[:limit]
        logger.info("Limited to %d source(s)", len(all_sources))

    return all_sources


# ---------------------------------------------------------------------------
# Crawl pipeline (focused web crawler → LLM extraction → DB upsert)
# ---------------------------------------------------------------------------


def _load_crawl_seeds(seeds_file: Optional[str]) -> List[str]:
    """Load seed URLs from a JSON file.

    The file format is a list of objects with a "url" key:
        [{"name": "...", "url": "https://...", ...}, ...]
    """
    import json
    from pathlib import Path

    if seeds_file:
        path = Path(seeds_file)
    else:
        path = Path(__file__).parent / "seeds.json"

    if not path.exists():
        logger.error("Seeds file not found: %s", path)
        return []

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    seeds = []
    for item in data:
        url = item.get("url", "").strip()
        if url:
            seeds.append(url)
    return seeds


async def run_dynamic_queue_pipeline(
    *,
    queue_limit: int = 20,
    max_depth: int = 2,
    max_pages_per_domain: int = 15,
    dry_run: bool = False,
    persist: bool = True,
    limit_extract: Optional[int] = None,
) -> dict:
    """Run the crawl pipeline using seeds from the Supabase crawler_seeds queue.

    Pulls the next batch of seeds from ``crawler_seeds``, runs the focused
    crawler + LLM extraction, marks each seed as crawled/failed, and enqueues
    any newly discovered directory hubs back into the queue.

    Returns a summary dict with crawl stats, ingestion results, and queue
    metadata.
    """
    from app.database import SessionLocal
    from .seed_queue import (
        enqueue_discovered_seeds,
        get_next_seed_batch,
        mark_seed_crawled,
        mark_seed_robots_denied,
    )

    logger.info("Fetching %d seed(s) from Supabase crawler_seeds queue", queue_limit)
    db = SessionLocal()
    seed_batch: list[dict] = []
    try:
        seed_batch = get_next_seed_batch(db, limit=queue_limit)
    finally:
        db.close()

    if not seed_batch:
        logger.warning("No queued seeds found in crawler_seeds table — nothing to crawl.")
        return {
            "queue_size": 0,
            "seeds_processed": 0,
            "candidates": [],
            "ingested": 0,
            "skipped_duplicates": 0,
            "extraction_failed": 0,
            "discovered_hubs_enqueued": 0,
        }

    logger.info("Retrieved %d seed(s) from Supabase crawler_seeds queue", len(seed_batch))
    for s in seed_batch:
        logger.info(
            "  [queue] %s (category=%s, priority=%d, status=%s, last_crawled=%s)",
            s["url"], s["category"], s["priority"], s["status"],
            s["last_crawled_at"] or "never",
        )

    seed_urls = [s["url"] for s in seed_batch]

    # Run the standard crawl pipeline on the dynamic batch
    summary = await run_crawl_pipeline(
        seed_urls,
        max_depth=max_depth,
        max_pages_per_domain=max_pages_per_domain,
        dry_run=dry_run,
        persist=persist,
        limit_extract=limit_extract,
    )

    # Mark seeds as crawled/failed and enqueue discovered hubs
    discovered_hubs = summary.get("discovered_hubs", [])
    hub_origins = summary.get("discovered_hub_origins", {})
    seed_results = summary.get("seed_results", {})
    hubs_enqueued = 0
    db = SessionLocal()
    try:
        for s in seed_batch:
            # Each seed's outcome is decided by its own root fetch — never by
            # batch-wide errors. A seed whose root page loaded is a success
            # even if unrelated child pages 404'd; a missing outcome is a
            # conservative failure so the seed is retried rather than stuck.
            res = seed_results.get(s["url"])
            if res is None:
                success = False
                error = "no crawl outcome recorded for seed"
            else:
                success = bool(res.get("success"))
                error = res.get("error") or None
            # A robots.txt denial is a policy outcome, not a broken site:
            # it must not accrue the transient-failure count that ends in
            # quarantine (C6.12). It lands in the robots path instead.
            robots_block = bool(error and error.startswith("robots"))
            if dry_run:
                logger.info("[dry-run] Would mark seed %s as crawled (success=%s, error=%s)",
                            s["id"], success, error)
            elif robots_block:
                mark_seed_robots_denied(db, s["id"], detail=error or "robots_denied")
            else:
                mark_seed_crawled(db, s["id"], success=success, error=error)

        # Enqueue newly discovered directory hubs
        if discovered_hubs and not dry_run:
            hubs_enqueued = 0
            for hub_url in discovered_hubs:
                # Parent = the actual page that surfaced the hub link; fall
                # back to a marker only when no origin was recorded.
                parent = hub_origins.get(hub_url) or "dynamic_queue"
                inserted = enqueue_discovered_seeds(
                    db, [hub_url], parent_url=parent,
                    detected_category="discovered_directory",
                )
                hubs_enqueued += inserted
        elif discovered_hubs and dry_run:
            logger.info("[dry-run] Would enqueue %d discovered hub(s):", len(discovered_hubs))
            for h in discovered_hubs[:10]:
                logger.info("  [dry-run] hub: %s", h)
            hubs_enqueued = len(discovered_hubs)
    finally:
        db.close()

    summary["queue_size"] = len(seed_batch)
    summary["seeds_processed"] = len(seed_batch)
    summary["discovered_hubs_enqueued"] = hubs_enqueued
    return summary


async def run_crawl_pipeline(
    seeds: List[str],
    *,
    max_depth: int = 2,
    max_pages_per_domain: int = 15,
    dry_run: bool = False,
    persist: bool = True,
    limit_extract: Optional[int] = None,
) -> dict:
    """Run the focused crawler, extract scholarships via LLM, and persist.

    Args:
        limit_extract: If set, only extract from the top N candidates by score
                       (conserves OpenAI API usage during testing).

    Returns a summary dict with crawl stats and ingestion results.
    """
    from .crawler import ScholarshipCrawler

    logger.info("Starting crawl with %d seed URL(s) (max_depth=%d, max_pages=%d)",
                len(seeds), max_depth, max_pages_per_domain)

    crawler = ScholarshipCrawler(
        seeds=seeds,
        max_depth=max_depth,
        max_pages_per_domain=max_pages_per_domain,
    )
    candidates = await crawler.crawl()
    stats = crawler.get_stats()

    logger.info("Crawl found %d candidate page(s)", len(candidates))

    if dry_run or not persist:
        for c in candidates:
            state_str = f", state={c.state_restriction}" if c.state_restriction else ""
            logger.info(
                "[dry-run] Candidate: %s (score=%d%s, keywords=%s, regional=%s)",
                c.url, c.relevance_score, state_str, c.matched_keywords[:5],
                c.regional_keywords[:3],
            )
        return {
            **stats.summary(),
            "candidates": [
                {
                    "url": c.url,
                    "title": c.title,
                    "relevance_score": c.relevance_score,
                    "matched_keywords": c.matched_keywords,
                    "regional_keywords": c.regional_keywords,
                    "state_restriction": c.state_restriction,
                    "depth": c.depth,
                }
                for c in candidates
            ],
            "ingested": 0,
            "skipped_duplicates": 0,
            "extraction_failed": 0,
        }

    # Persist: extract via LLM and upsert
    from app.database import SessionLocal
    from app.models.models import Scholarship

    # Sort candidates by score (highest first) and apply limit_extract cap
    candidates_sorted = sorted(candidates, key=lambda c: -c.relevance_score)
    if limit_extract is not None and limit_extract > 0:
        logger.info("Limiting LLM extraction to top %d of %d candidates (by score)",
                    limit_extract, len(candidates_sorted))
        candidates_sorted = candidates_sorted[:limit_extract]

    db = SessionLocal()
    ingested = created = updated = 0
    skipped_duplicates = 0
    extraction_failed = 0
    ext_stats = ExtractionStats()
    try:
        for c in candidates_sorted:
            # NOTE: no early portal_url skip — re-encountered opportunities are
            # re-extracted and re-verified so their facts stay fresh. Upsert
            # identity (C4) prevents duplicates.
            try:
                page = await extract_page(c.html, c.url, provider_hint=c.title or "",
                                          fetch_detail=_detail_fetcher())
            except Exception as exc:  # noqa: BLE001
                logger.error("Extraction failed for %s: %s", c.url, exc)
                extraction_failed += 1
                continue
            ext_stats.add(page)
            if page.error or (page.kind != PAGE_IRRELEVANT and not page.extracts):
                extraction_failed += 1
                logger.warning("No opportunities extracted from %s (%s)", c.url, page.error or page.kind)
                continue

            for extract in page.extracts:
                # Page-text state/metro heuristics (c.state_restriction,
                # "metro:..." regional keywords) are scoring signals only — they
                # are NOT written into eligibility restrictions. Ordinary prose
                # ("Applicants will be notified" -> Will County) must never create
                # a hard geographic exclusion.
                extract.source_name = c.title or c.url
                extract.source_category = "crawled"
                action = await _persist_extract(db, extract, c.url, multi=page.is_multi)
                if action == "created":
                    created += 1
                    ingested += 1
                elif action == "updated":
                    updated += 1
                    ingested += 1
                else:
                    extraction_failed += 1
                logger.info("[crawl] %s -> %s (%s)", c.url, extract.title, action)

        archived = archive_expired(db)
    finally:
        db.close()

    summary = {
        **stats.summary(),
        "ingested": ingested,
        "created": created,
        "updated": updated,
        "skipped_duplicates": skipped_duplicates,
        "extraction_failed": extraction_failed,
        "archived": archived,
        "extraction": ext_stats.summary(),
    }
    logger.info(
        "Crawl pipeline summary: pages=%d, candidates=%d, created=%d, updated=%d, failed=%d, extraction=%s",
        stats.pages_crawled, stats.candidates_found, created, updated, extraction_failed, ext_stats.summary(),
    )
    return summary


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


async def run_pipeline(
    target: str = "all",
    *,
    dry_run: bool = False,
    persist: bool = True,
    category: Optional[str] = None,
    state: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[ScrapeResult]:
    """Run the full three-tier pipeline for the given target and filters."""
    sources = _resolve_sources(target, category=category, state=state, limit=limit)
    logger.info(
        "Scraping %d source(s) (target=%s, category=%s, state=%s, limit=%s, dry_run=%s)",
        len(sources), target, category, state, limit, dry_run,
    )

    if not sources:
        logger.warning("No sources matched the given filters. Nothing to do.")
        return []

    ext_stats = ExtractionStats()
    results = await scrape_many(sources, stats=ext_stats)
    logger.info("Extraction: %s", ext_stats.summary())

    if dry_run or not persist:
        for r in results:
            logger.info("[%s] %s -> %s", r.status, r.url,
                        [e.title for e in r.extracts] if r.extracts else r.error)
        return results

    # Persist to DB — each opportunity independently.
    from app.database import SessionLocal

    db = SessionLocal()
    counts = {"created": 0, "updated": 0, "dead_link": 0, "error": 0}
    pages_failed = 0
    try:
        for r in results:
            if r.status in ("error",):
                pages_failed += 1
                logger.warning("Skipping %s: %s", r.url, r.error)
                continue
            for extract in r.extracts:
                action = await _persist_extract(db, extract, r.url, multi=r.is_multi)
                counts[action] = counts.get(action, 0) + 1
                logger.info("[%s] %s -> %s (%s)", r.status, r.url, extract.title, action)

        archived = archive_expired(db)
        logger.info("Auto-archival: %d expired scholarship(s) archived", archived)
    finally:
        db.close()

    logger.info("Summary: created=%d updated=%d dead_links=%d errors=%d pages_failed=%d archived=%d",
                counts["created"], counts["updated"], counts["dead_link"], counts["error"],
                pages_failed, archived)
    return results


# ---------------------------------------------------------------------------
# Registry-driven due-source pipeline (C7)
# ---------------------------------------------------------------------------


def _registry_source_config(src) -> SourceConfig:
    """Adapt a catalog_sources row to SourceConfig for the shared pipeline."""
    return SourceConfig(
        name=src.name, url=src.url, category=src.category,
        primary_discipline=src.primary_discipline or "any",
        target_credentials=list(src.target_credentials or []),
        state_restriction=src.state_restriction,
        scraper_type=src.scraper_type or "deterministic",
    )


async def run_due_sources_pipeline(
    *,
    limit: Optional[int] = None,
    dry_run: bool = False,
    db=None,
    source_keys: Optional[List[str]] = None,
) -> dict:
    """Check every due registered source, then extract only what changed.

    Per source: prime durable validators -> C6 fetch -> record health ->
    LLM-skip decision -> extract+persist on changed content, or advance
    last_seen_at on its opportunities when the page is unchanged.
    """
    from app.database import SessionLocal
    from app.models.models import Scholarship  # noqa: F401  (registry touches rows)
    from .fetch_policy import (
        FetchResult, OUTCOME_NETWORK_ERROR, OUTCOME_NOT_MODIFIED,
        content_hash, default_session,
    )
    from .fetcher import fetch_result
    from .source_registry import (
        classify_health, extraction_pending, get_due_sources, mark_extracted,
        mark_skipped, record_check, should_extract, touch_source_opportunities,
    )

    own_db = db is None
    db = db or SessionLocal()
    now = datetime.utcnow()
    counts = {
        "checked": 0, "healthy": 0, "redirected": 0, "not_found": 0,
        "transient": 0, "robots": 0, "access_denied": 0, "needs_review": 0,
        "extraction_attempted": 0, "extracted": 0, "skipped_unchanged": 0,
        "extraction_failed": 0, "rejected": 0, "records_needs_review": 0,
        "created": 0, "updated": 0, "dead_link": 0,
    }
    try:
        sources = get_due_sources(db, limit=limit, now=now,
                                  source_keys=source_keys)
        logger.info("Registry: %d due source(s)", len(sources))
        session = default_session()
        for src in sources:
            session.prime_validators(src.url, src.etag, src.last_modified)

        sem = asyncio.Semaphore(6)

        async def _one(src):
            async with sem:
                try:
                    res = await fetch_result(
                        src.url, scraper_type=src.scraper_type or "deterministic",
                        session=session)
                except Exception as exc:  # noqa: BLE001
                    res = FetchResult(url=src.url, outcome=OUTCOME_NETWORK_ERROR,
                                      error=type(exc).__name__)
                # A 304 that still owes extraction can't supply a body — do one
                # unconditional GET so pending content actually gets extracted.
                if res.outcome == OUTCOME_NOT_MODIFIED and extraction_pending(src):
                    res = await session.get(src.url, conditional=False)
                if res.ok and res.text and not res.content_hash:
                    res.content_hash = content_hash(res.text)  # playwright path
                return src, res

        pairs = await asyncio.gather(*(_one(s) for s in sources)) if sources else []

        for src, res in pairs:
            counts["checked"] += 1
            if dry_run:
                would_health = classify_health(src.health, res)
                do_extract, why = should_extract(src, res, now)
                logger.info("[dry-run] %s -> %s (health=%s) extract=%s:%s",
                            src.url, res.outcome, would_health, do_extract, why)
                continue

            health = record_check(db, src, res, now=now)
            if health == "healthy":
                counts["healthy"] += 1
            elif health == "redirected_or_moved":
                counts["redirected"] += 1
            elif health in ("permanent_not_found",):
                counts["not_found"] += 1
            elif health == "needs_url_review":
                counts["needs_review"] += 1
            elif health == "transient_failure":
                counts["transient"] += 1
            elif health.startswith("robots"):
                counts["robots"] += 1
            elif health == "access_denied":
                counts["access_denied"] += 1

            do_extract, why = should_extract(src, res, now)
            if do_extract:
                cfg = _registry_source_config(src)
                counts["extraction_attempted"] += 1
                try:
                    page = await extract_page(
                        res.text, src.url, provider_hint=src.name,
                        fetch_detail=_detail_fetcher(src.scraper_type))
                except Exception as exc:  # noqa: BLE001
                    logger.error("Extraction crashed for %s: %s — continuing", src.url, exc)
                    counts["extraction_failed"] += 1
                    continue
                counts["rejected"] += len(page.rejected)
                if page.error:
                    # A page-level extraction failure is not a success: the
                    # content stays pending (extracted_hash untouched) so the
                    # next check retries, and the failure lands in the totals.
                    counts["extraction_failed"] += 1
                    continue
                mark_extracted(db, src, res, now=now)
                counts["extracted"] += 1
                _apply_source_metadata(page.extracts, cfg, multi=page.is_multi)
                for extract in page.extracts:
                    if extract.verification_status == "needs_review":
                        counts["records_needs_review"] += 1
                    action = await _persist_extract(db, extract, src.url,
                                                    multi=page.is_multi)
                    counts[action] = counts.get(action, 0) + 1
                logger.info("[due] %s -> %d opportunity(ies) (%s)",
                            src.url, len(page.extracts), why)
            elif res.ok:
                mark_skipped(db, src, now=now)
                touched = touch_source_opportunities(db, src, now=now)
                counts["skipped_unchanged"] += 1
                logger.info("[due] %s unchanged (%s) — observed %d opportunity(ies)",
                            src.url, why, touched)
    finally:
        if own_db:
            db.close()

    logger.info("Due-source summary: %s", counts)
    return counts


# ---------------------------------------------------------------------------
# Daily scheduler
# ---------------------------------------------------------------------------


async def run_daily(at_hour: int = 3, at_minute: int = 0) -> None:
    """Run the pipeline once per day at the given local time."""
    logger.info("Daily scheduler started; will run at %02d:%02d local time", at_hour, at_minute)
    while True:
        now = datetime.now()
        next_run = now.replace(hour=at_hour, minute=at_minute, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        sleep_seconds = (next_run - now).total_seconds()
        logger.info("Next run at %s (in %.0f seconds)", next_run.isoformat(), sleep_seconds)
        await asyncio.sleep(sleep_seconds)
        try:
            await run_pipeline("all")
        except Exception as exc:  # noqa: BLE001
            logger.error("Daily run failed: %s", exc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_source_keys(raw: Optional[str], file_path: Optional[str]) -> Optional[List[str]]:
    """Resolve --source-keys / --source-keys-file into a key list.

    The file accepts a JSON array or a plain newline/comma-separated list.
    Returns None when nothing was provided (unscoped run)."""
    from pathlib import Path

    keys: List[str] = []
    if raw:
        keys.extend(k.strip() for k in raw.split(",") if k.strip())
    if file_path:
        text = Path(file_path).read_text(encoding="utf-8").strip()
        if text.startswith("["):
            keys.extend(str(k).strip() for k in json.loads(text) if str(k).strip())
        else:
            import re
            keys.extend(k for k in re.split(r"[\s,]+", text) if k)
    return keys or None


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: Optional[List[str]] = None) -> int:
    # Load .env from the backend directory so DATABASE_URL, OPENAI_API_KEY, etc.
    # are available when running the scraper as a standalone CLI.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        prog="scrapers.runner",
        description="GrantRx three-tier scraper runner",
    )
    parser.add_argument("--target", default="all", help="'all' or a specific URL")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to the database")
    parser.add_argument("--schedule", action="store_true", help="Run as a daily scheduler (blocks)")
    parser.add_argument("--hour", type=int, default=3, help="Daily run hour (default 03)")
    parser.add_argument("--minute", type=int, default=0, help="Daily run minute (default 00)")
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help=(
            "Filter sources by category. One of: national_association, "
            "federal_program, hospital_system, diversity_affinity, "
            "corporate_unrestricted, regional_foundation, honor_society"
        ),
    )
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="Filter regional sources by 2-letter state code (e.g. CA, NY, TX)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of sources processed in this run",
    )
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    parser.add_argument(
        "--crawl",
        action="store_true",
        help="Run the focused web crawler to discover new scholarship sources",
    )
    parser.add_argument(
        "--seeds-file",
        type=str,
        default=None,
        help="Path to a JSON file with seed URLs for crawling (default: scrapers/seeds.json)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=2,
        help="Maximum crawl depth from each seed (default 2)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=15,
        help="Maximum pages to crawl per domain (default 15)",
    )
    parser.add_argument(
        "--limit-extract",
        type=int,
        default=None,
        help="Cap LLM extraction to top N candidates by score (conserves API usage)",
    )
    parser.add_argument(
        "--dynamic-queue",
        action="store_true",
        help=(
            "Pull the next seed batch from the Supabase crawler_seeds queue "
            "instead of reading a static seeds.json file"
        ),
    )
    parser.add_argument(
        "--queue-limit",
        type=int,
        default=20,
        help="Number of seeds to pull from the dynamic queue (default 20)",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help=(
            "Import sources.json into the catalog_sources registry and "
            "seeds.json into the crawler_seeds queue (idempotent, C7)"
        ),
    )
    parser.add_argument(
        "--due",
        action="store_true",
        help="Run registry-scheduled checks for all due sources (C7)",
    )
    parser.add_argument(
        "--due-limit",
        type=int,
        default=None,
        help="Max number of due sources to check in this run",
    )
    parser.add_argument(
        "--source-keys",
        type=str,
        default=None,
        help="Comma-separated catalog source_keys to scope --due to",
    )
    parser.add_argument(
        "--source-keys-file",
        type=str,
        default=None,
        help="Path to a JSON array (or newline list) of source_keys for --due",
    )
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)

    if args.sync:
        from app.database import SessionLocal
        from .source_registry import sync_seeds, sync_sources

        db = SessionLocal()
        try:
            out = {
                "sources": sync_sources(db),
                "seeds": sync_seeds(db),
            }
        finally:
            db.close()
        print(json.dumps(out, indent=2, default=str))
        if not args.due:
            return 0

    if args.due:
        source_keys = _load_source_keys(args.source_keys, args.source_keys_file)
        summary = asyncio.run(
            run_due_sources_pipeline(
                limit=args.due_limit,
                dry_run=args.dry_run,
                source_keys=source_keys,
            )
        )
        print(json.dumps(summary, indent=2, default=str))
        return 0

    if args.schedule:
        asyncio.run(run_daily(at_hour=args.hour, at_minute=args.minute))
        return 0

    if args.dynamic_queue:
        summary = asyncio.run(
            run_dynamic_queue_pipeline(
                queue_limit=args.queue_limit,
                max_depth=args.max_depth,
                max_pages_per_domain=args.max_pages,
                dry_run=args.dry_run,
                limit_extract=args.limit_extract,
            )
        )
        print(json.dumps(summary, indent=2, default=str))
        return 0

    if args.crawl:
        seeds = _load_crawl_seeds(args.seeds_file)
        if not seeds:
            logger.error("No seeds loaded — nothing to crawl.")
            return 1
        summary = asyncio.run(
            run_crawl_pipeline(
                seeds,
                max_depth=args.max_depth,
                max_pages_per_domain=args.max_pages,
                dry_run=args.dry_run,
                limit_extract=args.limit_extract,
            )
        )
        print(json.dumps(summary, indent=2, default=str))
        return 0

    results = asyncio.run(
        run_pipeline(
            args.target,
            dry_run=args.dry_run,
            category=args.category,
            state=args.state,
            limit=args.limit,
        )
    )
    # Print a JSON summary to stdout for CLI consumers
    summary = [
        {
            "url": r.url,
            "status": r.status,
            "page_kind": r.page.kind if r.page else None,
            "error": r.error,
            "rejected": r.page.rejected if r.page else [],
            "opportunities": [
                {
                    "title": e.title,
                    "provider": e.provider,
                    "portal_url": e.portal_url,
                    "award_amount": e.award_amount,
                    "deadline": e.deadline,
                    "source": e.source,
                    "source_category": e.source_category,
                    "verification_status": getattr(e, "verification_status", None),
                }
                for e in r.extracts
            ],
        }
        for r in results
    ]
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
