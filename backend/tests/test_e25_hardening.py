"""E2.5 source-reliability & large-page hardening tests.

Covered:
- HTTP 403 -> access_denied, never permanent_not_found / archive / dead URL
- "all fields of pharmacy" -> pharmacy (subtree scope, never global 'any')
- community-foundation fund titles require applicant-facing education
  funding evidence or land in needs_review
- bounded chunked extraction for oversized listing pages
- run-level extraction metrics (attempted / succeeded / failed / rejected)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

import scrapers.runner as runner
from scrapers import source_registry as sr
from scrapers.extraction import (
    ExtractionLimits,
    PageExtraction,
    attach_verification,
    extract_page,
    _ANY_FIELD_EVIDENCE,
)
from scrapers.fetch_policy import (
    INCONCLUSIVE_OUTCOMES,
    OUTCOME_ACCESS_DENIED,
    OUTCOME_PERMANENT_HTTP,
    FetchPolicy,
    FetchResult,
    FetchSession,
)
from scrapers.llm_parser import LLMExtraction, LLMScholarship, llm_item_to_extract
from scrapers.schema import ScholarshipExtract
from scrapers.utils.taxonomy import normalize_field_of_study
from tests.conftest import FakeCatalogSession

NOW = datetime(2026, 3, 15, 12, 0, 0)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. HTTP 403 semantics
# ---------------------------------------------------------------------------

class _Server:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.get(str(request.url), httpx.Response(404))


def _session(responses) -> FetchSession:
    srv = _Server(responses)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(srv.handler), follow_redirects=True)
    return FetchSession(policy=FetchPolicy(min_interval=0.0), client=client), srv


def _src(**kw) -> SimpleNamespace:
    base = dict(
        source_key="s", name="S", url="https://a.example.org/x",
        category="national_association", primary_discipline="any",
        target_credentials=[], state_restriction=None,
        scraper_type="deterministic", enabled=True,
        check_interval_seconds=7 * 86400, peak_months=None,
        peak_interval_seconds=None, next_check_at=None,
        health=sr.HEALTH_UNKNOWN, consecutive_failures=0,
        consecutive_unchanged=0, last_error=None, last_resolved_url=None,
        last_attempted_at=None, last_fetch_ok_at=None, last_extracted_at=None,
        last_check_outcome=None, last_http_status=None,
        content_hash=None, extracted_hash=None, etag=None, last_modified=None,
        checks_total=0, extractions_total=0, skips_total=0,
        created_at=NOW, updated_at=NOW,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestHttp403:
    def test_403_maps_to_access_denied_not_permanent(self):
        session, srv = _session({
            "https://a.example.org/robots.txt": httpx.Response(404),
            "https://a.example.org/p": httpx.Response(403, text="denied"),
        })
        res = _run(session.get("https://a.example.org/p"))
        assert res.outcome == OUTCOME_ACCESS_DENIED
        assert res.http_status == 403
        assert res.outcome in INCONCLUSIVE_OUTCOMES
        # Bounded: a refusal is terminal within one run — no retry storm.
        assert len([r for r in srv.requests if r.url.path == "/p"]) == 1

    def test_404_still_permanent(self):
        session, _ = _session({
            "https://a.example.org/robots.txt": httpx.Response(404),
            "https://a.example.org/p": httpx.Response(404),
        })
        res = _run(session.get("https://a.example.org/p"))
        assert res.outcome == OUTCOME_PERMANENT_HTTP

    def test_classify_403_never_permanent_not_found(self):
        r = FetchResult(url="u", outcome=OUTCOME_ACCESS_DENIED, http_status=403)
        assert sr.classify_health(sr.HEALTH_HEALTHY, r) == sr.HEALTH_ACCESS_DENIED
        assert sr.classify_health(sr.HEALTH_UNKNOWN, r) == sr.HEALTH_ACCESS_DENIED
        assert sr.classify_health(sr.HEALTH_PERMANENT_NOT_FOUND, r) == sr.HEALTH_ACCESS_DENIED

    def test_repeated_403_stays_access_denied_never_review(self):
        src = _src(health=sr.HEALTH_ACCESS_DENIED)
        r = FetchResult(url="u", outcome=OUTCOME_ACCESS_DENIED, http_status=403)
        for _ in range(5):
            h = sr.apply_check(src, r, NOW)
        assert h == sr.HEALTH_ACCESS_DENIED
        assert src.next_check_at is not None            # still scheduled
        assert src.consecutive_failures == 0            # not a failure streak

    def test_403_recheck_is_bounded(self):
        src = _src()
        sr.apply_check(src, FetchResult(url="u", outcome=OUTCOME_ACCESS_DENIED,
                                        http_status=403), NOW)
        delta = (src.next_check_at - NOW).total_seconds()
        assert 0 < delta <= 30 * 86400                  # robots-scale recheck

    def test_403_then_real_404_still_tracks_death(self):
        # Access denial must not poison the later-dead path either.
        src = _src(health=sr.HEALTH_ACCESS_DENIED)
        sr.apply_check(src, FetchResult(url="u", outcome=OUTCOME_PERMANENT_HTTP,
                                        http_status=404), NOW)
        assert src.health == sr.HEALTH_PERMANENT_NOT_FOUND
        sr.apply_check(src, FetchResult(url="u", outcome=OUTCOME_PERMANENT_HTTP,
                                        http_status=404), NOW)
        assert src.health == sr.HEALTH_NEEDS_URL_REVIEW

    def test_403_portal_check_is_inconclusive_keeps_record(self):
        denied = FetchResult(url="u", outcome=OUTCOME_ACCESS_DENIED, http_status=403)

        async def _check(url, **kw):
            return denied

        with patch.object(runner, "_check_url_result", _check):
            url, valid, decisive = _run(runner._verify_portal_url(
                "https://a.example.org/apply", "https://a.example.org/src"))
        assert valid and not decisive   # opportunity preserved, nothing archived


# ---------------------------------------------------------------------------
# 2. Pharmacy-subtree normalization
# ---------------------------------------------------------------------------

class TestPharmacyScope:
    def test_all_fields_of_pharmacy_maps_to_pharmacy(self):
        assert normalize_field_of_study("all fields of pharmacy") == "pharmacy"
        assert normalize_field_of_study("All Pharmacy Fields") == "pharmacy"
        assert normalize_field_of_study("any major in nursing") == "nursing"

    def test_genuinely_unrestricted_maps_to_any(self):
        assert normalize_field_of_study("all fields of study") == "any"
        assert normalize_field_of_study("all majors") == "any"
        assert normalize_field_of_study("any discipline") == "any"
        assert normalize_field_of_study("any field of study") == "any"

    def test_unknown_scope_stays_unknown_never_any(self):
        assert normalize_field_of_study("xyzzy studies") is None
        assert normalize_field_of_study("all fields of quantumfloristics") is None

    def test_any_evidence_regex_rejects_subtree_phrase(self):
        assert not _ANY_FIELD_EVIDENCE.search("Open to all fields of pharmacy")
        assert not _ANY_FIELD_EVIDENCE.search("Students in any field of nursing")
        assert _ANY_FIELD_EVIDENCE.search("Open to all fields of study")
        assert _ANY_FIELD_EVIDENCE.search("All majors are eligible")

    def test_any_claim_rescoped_to_pharmacy_by_evidence(self):
        ex = ScholarshipExtract(
            title="Honor Society Award", provider="Honor Society",
            eligible_disciplines=["any"])
        ex = attach_verification(
            ex, text="Honor Society Award. Open to students in all fields of "
                     "pharmacy. Award $1,500 annually to students.",
            source_url="https://x.example.org/s")
        assert ex.eligible_disciplines == ["pharmacy"]

    def test_any_claim_without_evidence_still_flagged(self):
        ex = ScholarshipExtract(
            title="Vague Merit Award", provider="Some Foundation",
            eligible_disciplines=["any"])
        ex = attach_verification(
            ex, text="Vague Merit Award. Details vary.", source_url="https://x.org/a")
        assert ex.verification_status == "needs_review"


# ---------------------------------------------------------------------------
# 3. Community-foundation fund evidence
# ---------------------------------------------------------------------------

def _verified_candidate(title: str, evidence: str) -> ScholarshipExtract:
    ex = ScholarshipExtract(title=title, provider="Community Foundation")
    return attach_verification(ex, text=evidence, source_url="https://cf.example.org/f")


class TestCommunityFundEvidence:
    def test_named_fund_without_education_evidence_is_flagged(self):
        ex = _verified_candidate(
            "Angels Over Ballyhoo Fund",
            "Angels Over Ballyhoo Fund. Established 2008 to support community "
            "causes. Grant amount varies.")
        assert ex.verification_status == "needs_review"

    def test_donor_advised_fund_flagged(self):
        ex = _verified_candidate(
            "Smith Family Donor Advised Fund",
            "Smith Family Donor Advised Fund. Recommendations made annually "
            "by the donor family.")
        assert ex.verification_status == "needs_review"

    def test_memorial_endowment_without_education_terms_flagged(self):
        ex = _verified_candidate(
            "Harold Greene Memorial Endowment",
            "Harold Greene Memorial Endowment. Established in memory of "
            "Harold Greene to benefit the region.")
        assert ex.verification_status == "needs_review"

    def test_scholarship_fund_accepted(self):
        ex = _verified_candidate(
            "Brindle Family Scholarship Fund",
            "Brindle Family Scholarship Fund provides annual scholarships "
            "to graduating students pursuing higher education.")
        assert ex.verification_status == "verified"

    def test_fund_with_education_grant_language_accepted(self):
        ex = _verified_candidate(
            "Valley Teachers Fund",
            "Valley Teachers Fund makes education grants to classroom "
            "teachers in the district each school year.")
        assert ex.verification_status == "verified"

    def test_non_fund_title_unaffected(self):
        ex = _verified_candidate(
            "Community General Fund Drive",
            "Community General Fund Drive — wait this has Fund too")
        assert ex.verification_status == "needs_review"  # still gated


# ---------------------------------------------------------------------------
# 4. Bounded chunked extraction
# ---------------------------------------------------------------------------

BIG_URL = "https://big.example.org/scholarships"


def _big_listing(n_sections: int = 8, pad_chars: int = 4200) -> str:
    parts = ["<html><body><h1>Big Foundation Scholarships</h1>"]
    pad = "Background information about our programs. " * (pad_chars // 42)
    for i in range(n_sections):
        parts.append(
            f"<div><h2>Program Area {i}</h2>"
            f"<div class='card'><h3>Section {i} Scholarship</h3>"
            f"<p>Award $1,000. Deadline June 1, 2027. For students.</p>"
            f"<a href='/s{i}'>Learn more</a></div>"
            f"<p>{pad}</p></div>")
    parts.append("</body></html>")
    return "".join(parts)


def _chunk_aware_llm(sections: int, calls: list, *, fail_markers=(), shared=None):
    """LLM stand-in: returns the Section i item only when that section's text
    is inside the chunk fragment it was given."""
    async def _fake(html, url, *, mode="listing", max_items=25):
        calls.append(html)
        if any(m in html for m in fail_markers):
            return None
        items = []
        for i in range(sections):
            if f"Section {i} Scholarship" in html:
                items.append(dict(title=f"Section {i} Scholarship",
                                  provider="Big Foundation", award_amount=1000,
                                  deadline="2027-06-01", detail_url=f"/s{i}"))
        if shared:
            items.append(dict(shared))
        return LLMExtraction(
            extracts=[llm_item_to_extract(LLMScholarship(**d), url) for d in items])
    return _fake


class TestChunkedExtraction:
    def test_ordinary_page_single_call_not_chunked(self):
        calls = []
        html = ("<html><body><h1>Two Awards</h1>"
                "<div><h3>Alpha Scholarship</h3><p>$1,000 for students. "
                "Deadline June 1, 2027.</p></div>"
                "<div><h3>Beta Scholarship</h3><p>$2,000 for students. "
                "Deadline July 1, 2027.</p></div></body></html>")
        with patch("scrapers.llm_parser.extract_opportunities_with_llm",
                   _chunk_aware_llm(0, calls)):
            pass
        # Use the standard factory: small page -> one call.
        async def _one(html_, url, *, mode="listing", max_items=25):
            calls.append(url)
            return LLMExtraction(extracts=[])
        with patch("scrapers.llm_parser.extract_opportunities_with_llm", _one):
            page = _run(extract_page(html, BIG_URL, limits=ExtractionLimits()))
        assert len(calls) == 1
        assert page.chunked is False

    def test_large_page_chunks_deterministically(self):
        html = _big_listing()
        calls = []
        with patch("scrapers.llm_parser.extract_opportunities_with_llm",
                   _chunk_aware_llm(8, calls)):
            page = _run(extract_page(html, BIG_URL, limits=ExtractionLimits()))
        assert page.chunked is True
        assert 2 <= page.chunk_stats["calls"] <= 5   # bounded
        assert page.chunk_stats["calls"] == page.chunk_stats["chunks"]
        assert len(page.extracts) >= 2
        assert all(e.title.endswith("Scholarship") for e in page.extracts)

    def test_cross_chunk_duplicates_dedupe(self):
        html = _big_listing()
        calls = []
        shared = dict(title="Shared Spine Scholarship", provider="Big Foundation",
                      award_amount=500, deadline="2027-06-01")
        # The item exists in every chunk's view -> the merge must dedupe it.
        html = html.replace("</body>",
                            "<div><h3>Shared Spine Scholarship</h3>"
                            "<p>$500 for students.</p></div></body>")
        with patch("scrapers.llm_parser.extract_opportunities_with_llm",
                   _chunk_aware_llm(8, calls, shared=shared)):
            page = _run(extract_page(html, BIG_URL, limits=ExtractionLimits()))
        titles = [e.title for e in page.extracts]
        assert titles.count("Shared Spine Scholarship") == 1
        assert page.chunk_stats["cross_chunk_duplicates"] >= 1

    def test_chunk_cap_enforced(self):
        html = _big_listing(n_sections=12, pad_chars=6000)
        calls = []
        limits = ExtractionLimits(max_chunks_per_page=2, chunk_max_chars=8000)
        with patch("scrapers.llm_parser.extract_opportunities_with_llm",
                   _chunk_aware_llm(12, calls)):
            page = _run(extract_page(html, BIG_URL, limits=limits))
        assert page.chunked is True
        assert page.chunk_stats["calls"] <= 2
        assert len(calls) <= 2

    def test_failed_chunk_does_not_fabricate(self):
        html = _big_listing()
        calls = []
        with patch("scrapers.llm_parser.extract_opportunities_with_llm",
                   _chunk_aware_llm(8, calls, fail_markers=("Program Area 3",))):
            page = _run(extract_page(html, BIG_URL, limits=ExtractionLimits()))
        assert page.error is None                     # partial failure tolerated
        assert page.chunk_stats["failed_chunks"] >= 1
        assert not any(e.title == "Section 3 Scholarship" for e in page.extracts)

    def test_all_chunks_failed_is_extraction_failure(self):
        html = _big_listing()
        with patch("scrapers.llm_parser.extract_opportunities_with_llm",
                   _chunk_aware_llm(8, [], fail_markers=("Program Area",))):
            page = _run(extract_page(html, BIG_URL, limits=ExtractionLimits()))
        assert page.error == "LLM extraction failed"
        assert page.extracts == []

    def test_chunk_titles_still_evidence_bound(self):
        html = _big_listing()
        calls = []

        async def _hallucinating(html_, url, *, mode="listing", max_items=25):
            calls.append(url)
            item = dict(title="Invented Phantom Scholarship",
                        provider="Big Foundation", award_amount=99999)
            return LLMExtraction(
                extracts=[llm_item_to_extract(LLMScholarship(**item), url)])

        with patch("scrapers.llm_parser.extract_opportunities_with_llm",
                   _hallucinating):
            page = _run(extract_page(html, BIG_URL, limits=ExtractionLimits()))
        assert page.extracts == []
        assert any(r[1] == "title_not_on_page" for r in page.rejected)

    def test_directory_page_never_chunked(self):
        """A directory page keeps the E1.5 track path even when large."""
        tracks = "".join(
            f'<a href="/loans/t{i}.html">Track {i} Profession</a>' for i in range(4))
        pad = "program background. " * 1500
        html = (f"<html><body><h1>State Loan Forgiveness Program</h1><p>{pad}</p>"
                f"<h2>Eligible Professions and Guidelines</h2><div>{tracks}</div>"
                f"</body></html>")
        calls = []

        async def _llm(html_, url, *, mode="listing", max_items=25):
            calls.append(url)
            return None
        with patch("scrapers.llm_parser.extract_opportunities_with_llm", _llm):
            page = _run(extract_page(html, "https://s.example.org/loans/index.html",
                                     provider_hint="State",
                                     limits=ExtractionLimits()))
        assert page.chunked is False
        parent = page.extracts[0]
        assert len(parent.tracks) == 4


# ---------------------------------------------------------------------------
# 5. Run-level metrics
# ---------------------------------------------------------------------------

class TestRunMetrics:
    def _due_src(self):
        return _src(url="https://a.example.org/x")

    def _patch_pipeline(self, page):
        return [
            patch("scrapers.source_registry.get_due_sources",
                  return_value=[self._due_src()]),
            patch("scrapers.source_registry.extraction_pending", return_value=False),
            patch("scrapers.source_registry.record_check", return_value="healthy"),
            patch("scrapers.source_registry.mark_extracted"),
            patch("scrapers.source_registry.mark_skipped"),
            patch("scrapers.source_registry.touch_source_opportunities",
                  return_value=0),
            patch("scrapers.runner.extract_page",
                  new=lambda *a, **kw: _coro(page)),
            patch("scrapers.runner._persist_extract",
                  new=lambda *a, **kw: _coro("created")),
        ]

    def test_page_error_counts_extraction_failed(self):
        page = PageExtraction(url="https://a.example.org/x", kind="listing",
                              error="LLM extraction failed")

        async def _fetch(*a, **kw):
            return FetchResult(url="https://a.example.org/x", outcome="ok",
                               http_status=200, text="<html/>", content_hash="h")

        patches = self._patch_pipeline(page)
        patches += [
            patch("scrapers.fetcher.fetch_result", _fetch),
            patch("scrapers.fetch_policy.default_session",
                  return_value=FetchSession(policy=FetchPolicy(min_interval=0))),
        ]
        for p in patches:
            p.start()
        try:
            counts = _run(runner.run_due_sources_pipeline(db=FakeCatalogSession()))
        finally:
            for p in patches:
                p.stop()
        assert counts["extraction_attempted"] == 1
        assert counts["extraction_failed"] == 1
        assert counts["extracted"] == 0
        assert counts["created"] == 0


async def _coro(value):
    return value
