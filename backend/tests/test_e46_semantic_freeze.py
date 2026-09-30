"""E4.6 semantic-freeze regressions.

- federal_agency provider type (additive; other values untouched)
- funding type from an OFFICIAL title's own instrument head noun only
- employment_required vs post-award service commitment (prompt contract)
- review engine never works sticky-archived records; deadline_passed only
  via the explicit current-cycle path
"""

import asyncio

import pytest

from app.models.models import Scholarship
from scrapers import llm_parser
from scrapers.extraction import _apply_title_funding_terms
from scrapers.fetch_policy import OUTCOME_OK, FetchResult
from scrapers.review import (
    ARCHIVED_EXCLUDED,
    ARCHIVED_SKIP,
    EXCLUDED_ARCHIVE_REASONS,
    queue_category,
    reevaluate_record,
    run_clearance,
)
from scrapers.schema import ScholarshipExtract
from scrapers.utils.taxonomy import (
    explicit_funding_type_in_text,
    funding_type_from_program_title,
    normalize_provider_type,
)


# ---------------------------------------------------------------------------
# Decision 1 — federal_agency
# ---------------------------------------------------------------------------

class TestFederalProviderType:
    @pytest.mark.parametrize("raw", ["federal_agency", "Federal Agency", "federal_government",
                                     "U.S. Government", "federal"])
    def test_federal_spellings_normalize(self, raw):
        assert normalize_provider_type(raw) == "federal_agency"

    @pytest.mark.parametrize("raw", ["national_association", "state_agency", "corporate",
                                     "community_foundation"])
    def test_other_values_pass_through(self, raw):
        assert normalize_provider_type(raw) == raw

    def test_unknown_stays_unknown(self):
        assert normalize_provider_type(None) is None
        assert normalize_provider_type("  ") is None

    def test_prompt_offers_federal_agency(self):
        assert "'federal_agency'" in llm_parser.SYSTEM_PROMPT
        assert "federal_agency" in llm_parser.LLMScholarship.model_fields["provider_type"].description

    def test_llm_item_maps_federal_type(self):
        item = llm_parser.LLMScholarship(
            title="Boren Fellowship", provider="DLNSEO", provider_type="federal government")
        assert llm_parser.llm_item_to_extract(item, "https://x.gov/").provider_type == "federal_agency"


# ---------------------------------------------------------------------------
# Decision 2 — official title head noun
# ---------------------------------------------------------------------------

class TestTitleFundingType:
    @pytest.mark.parametrize("title,expected", [
        ("Paul Tsongas Scholarship", "scholarship"),
        ("Massachusetts Cash Grant", "grant"),
        ("AMS Graduate Fellowship in the History of Science", None),  # head is 'Science'
        ("AMS Graduate Fellowship", "fellowship"),
        ("Behavioral Health Workforce Scholarship Program", "scholarship"),
        ("Texas Educational Opportunity Grant (TEOG)", "grant"),
        ("Washington College Grant (WA Grant)", "grant"),
        ("Future Ready Iowa Last-Dollar Scholarship", "scholarship"),
    ])
    def test_head_noun(self, title, expected):
        assert funding_type_from_program_title(title) == expected

    @pytest.mark.parametrize("title", [
        "Scholarship", "Fellowship", "Grant",                 # no program identity
        "WAI2027 Scholarships", "Army Nursing Scholarships",  # plural = category heading
        "Grant Program for Dependents of Police Officers",     # noun not the head
        "MASSGrant", "Hathaway",                               # compound / no noun
        "Dinah Eng Leadership Fellowship Grant",               # mixed instruments
        "Stanford Chen Internship Grant",                      # internship ambiguity
        "Aerospace Loan Grant", "Scholarship Award",           # loan / award wording
        "Scholarship America", "Thurgood Marshall College Fund",
        "", None,
    ])
    def test_ambiguous_or_absent_stays_unknown(self, title):
        assert funding_type_from_program_title(title) is None

    def test_loan_forgiveness_precedence_kept(self):
        assert funding_type_from_program_title("Nursing Student Loan Forgiveness Program") == "loan_repayment"

    def test_label_text_helper_unchanged(self):
        # E1.5 contract for arbitrary label text is untouched.
        assert explicit_funding_type_in_text("Community Merit Scholarship") is None

    def test_extracted_type_wins(self):
        ex = ScholarshipExtract(title="Teacher Education Grant", funding_type="service_contingent")
        _apply_title_funding_terms(ex)
        assert ex.funding_type == "service_contingent"

    def test_applied_only_when_null(self):
        ex = ScholarshipExtract(title="Paul Tsongas Scholarship")
        _apply_title_funding_terms(ex)
        assert ex.funding_type == "scholarship"


# ---------------------------------------------------------------------------
# Decision 4 — yearless recurring dates never reopen / never become deadlines
# ---------------------------------------------------------------------------

class TestYearlessRecurringDates:
    def _archived(self, **kw):
        from datetime import date
        from app.services import lifecycle
        s = Scholarship(title="Hawai'i Promise Program", provider="UHCC",
                        deadline=date(2024, 3, 1), lifecycle_status="published",
                        archive_reason=None, is_archived=False)
        lifecycle.archive(s, "deadline_passed")
        for k, v in kw.items():
            setattr(s, k, v)
        return s

    def test_null_deadline_refresh_keeps_deadline_passed_archived(self):
        from app.services import lifecycle
        s = self._archived(deadline=None)
        lifecycle.apply_refresh(s, destination_verified=True)
        assert s.lifecycle_status == "archived" and s.archive_reason == "deadline_passed"

    def test_past_deadline_refresh_stays_archived(self):
        from app.services import lifecycle
        s = self._archived()
        lifecycle.apply_refresh(s, destination_verified=True)
        assert s.lifecycle_status == "archived"

    def test_specific_future_cycle_reopens(self):
        from datetime import date, timedelta
        from app.services import lifecycle
        s = self._archived(deadline=date.today() + timedelta(days=120))
        lifecycle.apply_refresh(s, destination_verified=True)
        assert s.lifecycle_status == "published"

    def test_yearless_date_is_not_assigned_a_year(self):
        from scrapers.extraction import _deadline_year_supported
        page = "Submit the FAFSA by the priority deadline of March 1 for first consideration."
        assert _deadline_year_supported("2027-03-01", page) is None

    def test_review_engine_skips_deadline_passed_by_default(self):
        s = self._archived(deadline=None, verification_status="needs_review")
        assert queue_category(s, [], []) == ARCHIVED_SKIP


# ---------------------------------------------------------------------------
# Decision 5 — service vs employment
# ---------------------------------------------------------------------------

class TestServiceVsEmployment:
    def test_prompt_separates_post_award_service(self):
        desc = llm_parser.LLMScholarship.model_fields["employment_required"].description
        assert "AFTER receiving" in desc and "NOT" in desc
        assert "not employment_required" in llm_parser.SYSTEM_PROMPT

    def test_flags_are_independent_in_mapping(self):
        item = llm_parser.LLMScholarship(
            title="Nursing Student Loan", provider="HEAB",
            employment_required=False, has_service_commitment=True,
            service_commitment_duration_months=24)
        ex = llm_parser.llm_item_to_extract(item, "https://heab.example.gov/")
        assert ex.employment_required is False
        assert ex.has_service_commitment is True


# ---------------------------------------------------------------------------
# Decision 6 — review engine archive exclusion
# ---------------------------------------------------------------------------

def _row(**kw):
    base = dict(
        title="Alpha Scholarship", provider="Example Foundation",
        portal_url="https://cf.example.org/scholarships",
        source_url="https://cf.example.org/scholarships",
        award_amount=None, deadline=None, min_gpa=0.0, eligible_disciplines=["any"],
        is_general_major=True, verification_status="needs_review",
        verified_fields={"title": "verified", "award_amount": "not_asserted",
                         "deadline": "not_asserted", "min_gpa": "not_asserted"},
        lifecycle_status="published", archive_reason=None, is_archived=False,
        extraction_method="llm", estimated_next_cycle=None,
    )
    base.update(kw)
    return Scholarship(**base)


PAGE = "<html><body><h1>Alpha Scholarship</h1><p>Open to all majors.</p></body></html>"


async def _fetch(url):
    return FetchResult(url=url, outcome=OUTCOME_OK, http_status=200, text=PAGE)


class TestReviewArchiveExclusion:
    @pytest.mark.parametrize("reason", sorted(EXCLUDED_ARCHIVE_REASONS))
    def test_sticky_archive_queue(self, reason):
        row = _row(lifecycle_status="archived", archive_reason=reason, is_archived=True)
        assert queue_category(row, [], []) == ARCHIVED_EXCLUDED

    def test_deadline_passed_still_skip_category(self):
        row = _row(lifecycle_status="archived", archive_reason="deadline_passed", is_archived=True)
        assert queue_category(row, [], []) == ARCHIVED_SKIP

    @pytest.mark.parametrize("reason", sorted(EXCLUDED_ARCHIVE_REASONS))
    def test_reevaluate_never_verifies_sticky_archive(self, reason):
        row = _row(lifecycle_status="archived", archive_reason=reason, is_archived=True)
        out = asyncio.run(reevaluate_record(row, fetch=_fetch))
        assert out.action == "skipped" and not out.cleared
        assert row.verification_status == "needs_review"

    def test_published_record_still_clears(self):
        row = _row()
        out = asyncio.run(reevaluate_record(row, fetch=_fetch))
        assert out.action == "verified"


class _Q:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


def test_run_clearance_excludes_sticky_even_with_include_archived(monkeypatch):
    import scrapers.review as review

    backlog = [
        {"id": "a", "source_url": "u", "title": "A", "queue": ARCHIVED_EXCLUDED},
        {"id": "b", "source_url": "u", "title": "B", "queue": ARCHIVED_SKIP},
    ]
    worked = []

    async def fake_reeval(row, **kw):
        worked.append(row)
        return review.ReviewOutcome(action="gated")

    class DB:
        def query(self, *a):
            return _Q([])

    monkeypatch.setattr(review, "classify_backlog", lambda db: backlog)
    monkeypatch.setattr(review, "_source_discipline_map", lambda db: {})
    monkeypatch.setattr(review, "reevaluate_record", fake_reeval)

    res = asyncio.run(run_clearance(DB(), dry_run=True, session=object()))
    assert res["classified"] == 0
    res = asyncio.run(run_clearance(DB(), dry_run=True, include_archived=True, session=object()))
    assert res["classified"] == 1  # deadline_passed only, via explicit opt-in
