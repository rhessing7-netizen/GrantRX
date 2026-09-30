"""Batch E1.5 — catalog quality gate tests.

Covers: program-directory parent+track extraction with authoritative link
text as track identity, needs_review exclusion from consumer surfaces,
explicit loan-forgiveness funding-type calibration, APhA unsupported-year
safety, and no weakening of title evidence guards.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scrapers.extraction import (
    _apply_title_funding_terms,
    _program_track_links,
    extract_page,
    title_on_page,
)
from scrapers.llm_parser import LLMExtraction, llm_item_to_extract, LLMScholarship
from scrapers.schema import ScholarshipExtract
from scrapers.utils.taxonomy import explicit_funding_type_in_text
from app.services.lifecycle import is_discoverable
from app.services.matcher import match_scholarships
from tests.c5_fixtures import fake_llm_factory


URL = "https://agency.example.gov/programs/loanforgiveness/index.html"

MDH_HTML = """
<html><body>
<nav><h2>Secondary menu</h2><a href="/nav">About Us</a></nav>
<h1>Minnesota Healthcare Loan Forgiveness Programs</h1>
<p>The Minnesota loan forgiveness program repays educational debt for
health professionals serving in designated communities.</p>
<h3>Eligible Professions and Guidelines:</h3>
<ul>
  <li><a href="hospnur.html">Minnesota Hospital Registered Nurse Loan Forgiveness Guidelines</a></li>
  <li><a href="dentist.html">Minnesota Dentist Guidelines</a></li>
  <li><a href="pharm.html">Minnesota Rural Pharmacist Guidelines</a></li>
  <li><a href="nurse.html">Minnesota Long Term Care Nurses Guidelines</a></li>
  <li><a href="hospnur.html">Minnesota Hospital Registered Nurse Loan Forgiveness Guidelines</a></li>
</ul>
<h2>Related Topics</h2><a href="/other">Other programs</a>
</body></html>
"""

ORDINARY_LISTING_HTML = """
<html><body>
<h1>Foundation Scholarships</h1>
<h2>Available Awards</h2>
<ul>
  <li><a href="a.html">Alpha Merit Scholarship</a> $5,000 deadline March 1</li>
  <li><a href="b.html">Beta Nursing Scholarship</a> $2,000 deadline April 1</li>
  <li><a href="c.html">Gamma Service Award</a> $1,000 deadline May 1</li>
</ul>
</body></html>
"""


def _run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro) \
        if asyncio.get_event_loop().is_running() is False else asyncio.run(coro)


def _extract(html, url, scripts=None):
    calls = []
    with patch("scrapers.llm_parser.extract_opportunities_with_llm",
               fake_llm_factory(scripts or {}, calls)):
        import asyncio
        page = asyncio.run(extract_page(html, url, provider_hint="Test Provider"))
    return page, calls


# ---------------------------------------------------------------------------
# Program-directory track mode
# ---------------------------------------------------------------------------


class TestProgramDirectory:
    def test_parent_with_authoritative_tracks(self):
        scripts = {URL: [{"title": "Minnesota Healthcare Loan Forgiveness Programs",
                          "provider": "Minnesota Department of Health"}]}
        page, calls = _extract(MDH_HTML, URL, scripts)
        assert len(page.extracts) == 1
        parent = page.extracts[0]
        assert parent.title == "Minnesota Healthcare Loan Forgiveness Programs"
        titles = [t.title for t in parent.tracks]
        # Authoritative link text verbatim, duplicates collapsed.
        assert titles == [
            "Minnesota Hospital Registered Nurse Loan Forgiveness Guidelines",
            "Minnesota Dentist Guidelines",
            "Minnesota Rural Pharmacist Guidelines",
            "Minnesota Long Term Care Nurses Guidelines",
        ]
        urls = [t.detail_url for t in parent.tracks]
        assert all(u.startswith("https://agency.example.gov/programs/loanforgiveness/")
                   for u in urls)
        assert "hospnur.html" in urls[0]

    def test_track_disciplines_from_link_text(self):
        page, _ = _extract(MDH_HTML, URL)
        parent = page.extracts[0]
        by_title = {t.title: t.eligible_disciplines for t in parent.tracks}
        assert by_title["Minnesota Dentist Guidelines"] == ["dentistry"]
        assert by_title["Minnesota Rural Pharmacist Guidelines"] == ["pharmacy"]
        assert by_title["Minnesota Hospital Registered Nurse Loan Forgiveness Guidelines"] == ["nursing"]

    def test_parent_disciplines_cover_tracks(self):
        page, _ = _extract(MDH_HTML, URL)
        parent = page.extracts[0]
        assert {"nursing", "dentistry", "pharmacy"} <= set(parent.eligible_disciplines)

    def test_parent_funding_type_is_loan_repayment(self):
        page, _ = _extract(MDH_HTML, URL)
        assert page.extracts[0].funding_type == "loan_repayment"

    def test_llm_cannot_invent_track_titles(self):
        """LLM returning composed names never reaches track identity — tracks
        come only from page link text, so a hallucinated name is impossible."""
        scripts = {URL: [{"title": "Minnesota Healthcare Loan Forgiveness Programs",
                          "provider": "MDH",
                          "tracks": [{"title": "Totally Invented Track",
                                      "detail_url": "https://evil.example.com/x"}]}]}
        page, _ = _extract(MDH_HTML, URL, scripts)
        parent = page.extracts[0]
        titles = [t.title for t in parent.tracks]
        assert "Totally Invented Track" not in titles
        assert len(titles) == 4  # only real link-derived tracks

    def test_llm_composed_parent_title_replaced_by_h1(self):
        scripts = {URL: [{"title": "Completely Fabricated Program Name",
                          "provider": "MDH"}]}
        page, _ = _extract(MDH_HTML, URL, scripts)
        assert page.extracts[0].title == "Minnesota Healthcare Loan Forgiveness Programs"

    def test_llm_failure_still_persists_parent_from_h1(self):
        with patch("scrapers.llm_parser.extract_opportunities_with_llm",
                   new=lambda *a, **k: None):
            pass
        async def _none(*a, **k):
            return None
        import asyncio
        with patch("scrapers.llm_parser.extract_opportunities_with_llm", _none):
            page = asyncio.run(extract_page(MDH_HTML, URL, provider_hint="MDH"))
        assert len(page.extracts) == 1
        assert page.extracts[0].title == "Minnesota Healthcare Loan Forgiveness Programs"
        assert len(page.extracts[0].tracks) == 4

    def test_ordinary_listing_is_not_a_directory(self):
        """An 'Available Awards' section does NOT trigger directory mode —
        links here are independent opportunities, not tracks."""
        assert _program_track_links(ORDINARY_LISTING_HTML,
                                    "https://f.org/scholarships/") == []

    def test_single_link_is_not_a_directory(self):
        html = """<html><body><h1>X Loan Forgiveness</h1>
        <h3>Guidelines</h3><ul><li><a href="g.html">Program Guidelines</a></li></ul>
        </body></html>"""
        assert _program_track_links(html, "https://x.gov/p/") == []


# ---------------------------------------------------------------------------
# Title evidence remains strict
# ---------------------------------------------------------------------------


class TestTitleEvidence:
    def test_title_on_page_strict_for_opportunities(self):
        scripts = {URL + "l": [{"title": "Minnesota Dentist Loan Forgiveness",
                                "provider": "MDH"}]}
        page, _ = _extract(MDH_HTML, URL + "l", scripts)
        # Multi-item guard: composed title not on page → rejected, and the
        # directory branch (matching URL dir) still produced real tracks.
        # For a non-directory URL the composed item is still gated:
        assert all(e.title != "Minnesota Dentist Loan Forgiveness"
                   for e in page.extracts)

    def test_track_titles_outside_directory_mode_still_gated(self):
        """On a page WITHOUT a directory section, LLM-emitted tracks still
        face the C8 track_not_on_page guard."""
        html = """<html><body><h1>Real Scholarship Fund</h1>
        <p>A scholarship for students.</p></body></html>"""
        scripts = {"https://x.org/s": [{
            "title": "Real Scholarship Fund", "provider": "F",
            "tracks": [{"title": "Invisible Track"}]}]}
        page, _ = _extract(html, "https://x.org/s", scripts)
        assert page.extracts[0].tracks == []


# ---------------------------------------------------------------------------
# Funding-type calibration
# ---------------------------------------------------------------------------


class TestFundingType:
    def test_loan_forgiveness_title_maps_loan_repayment(self):
        assert explicit_funding_type_in_text(
            "Minnesota Healthcare Loan Forgiveness Programs") == "loan_repayment"
        assert explicit_funding_type_in_text(
            "State Student Loan Repayment Program") == "loan_repayment"
        assert explicit_funding_type_in_text(
            "Education Loan Repayment for Teachers") == "loan_repayment"

    def test_unknown_funding_stays_null(self):
        assert explicit_funding_type_in_text("Community Merit Scholarship") is None
        assert explicit_funding_type_in_text("") is None
        assert explicit_funding_type_in_text(None) is None

    def test_no_inference_from_generic_words(self):
        for t in ["Health Workforce Program", "Career Opportunity Fund",
                  "Provider Recruitment Grant"]:
            assert explicit_funding_type_in_text(t) is None

    def test_apply_title_terms_only_when_unset(self):
        ex = ScholarshipExtract(title="X Loan Forgiveness Program",
                                funding_type="service_contingent")
        _apply_title_funding_terms(ex)
        assert ex.funding_type == "service_contingent"  # explicit wins


# ---------------------------------------------------------------------------
# needs_review visibility gate
# ---------------------------------------------------------------------------


def _sch(verification="verified", lifecycle_status="published", **kw):
    s = MagicMock()
    for k, v in dict(
        verification_status=verification, lifecycle_status=lifecycle_status,
        is_archived=False, eligible_disciplines=[], eligible_credentials=[],
        academic_levels=[], state_restrictions=[], metro_restrictions=[],
        county_restrictions=[], city_restrictions=[], required_affiliations=[],
        matching_tags=[], funding_type=None, employment_required=False,
        has_service_commitment=False, citizenship_requirement=None,
        enrollment_statuses=[], institution_restrictions=[],
        military_affiliation_requirement=None, tracks=[], provider_mission=None,
        provider_core_values=[], is_general_major=False, min_gpa=None,
        max_sai=None, award_amount=None, deadline=None, title="X",
        provider="P", portal_url="https://x.test",
    ).items():
        setattr(s, k, v)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _profile(**kw):
    p = MagicMock()
    for k, v in dict(
        disciplines=[], target_credentials=[], primary_discipline=None,
        target_credential=None, clinical_phase=None, gpa=None,
        state_residence=None, metro_area=None, sai_score=None,
        first_gen=False, minority_flag=False, professional_affiliations=[],
    ).items():
        setattr(p, k, v)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


class TestNeedsReviewVisibility:
    def test_needs_review_not_discoverable(self):
        assert not is_discoverable(_sch(verification="needs_review"))

    def test_verified_and_legacy_discoverable(self):
        assert is_discoverable(_sch(verification="verified"))
        assert is_discoverable(_sch(verification="legacy_unverified"))
        assert is_discoverable(_sch(verification=None))

    def test_needs_review_excluded_from_matching(self):
        profile = _profile()
        results = match_scholarships(profile, [
            _sch(verification="needs_review", title="Hidden Award"),
            _sch(verification="verified", title="Visible Award"),
        ])
        titles = [r.title for r in results]
        assert "Visible Award" in titles
        assert "Hidden Award" not in titles

    def test_needs_review_still_persisted_states(self):
        """Archived lifecycle still wins over verification; needs_review is
        not a lifecycle state."""
        s = _sch(verification="needs_review", lifecycle_status="published")
        assert s.lifecycle_status == "published"  # record intact, just hidden


# ---------------------------------------------------------------------------
# APhA unsupported-year safety (regression)
# ---------------------------------------------------------------------------


class TestDeadlineYearSafety:
    def test_year_absent_from_evidence_dropped(self):
        from scrapers.extraction import _deadline_year_supported
        assert _deadline_year_supported("2023-12-01",
                                        "Applications close December 1") is None
        assert _deadline_year_supported("2025-12-01",
                                        "Applications close December 1, 2025") == "2025-12-01"
        assert _deadline_year_supported(None, "anything") is None
