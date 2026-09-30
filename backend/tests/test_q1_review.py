"""Q1 Catalog Review & Clearance Engine tests.

Covers the deterministic review-reason classifier, the re-evaluation
pipeline (same verification engine as extraction — never a weaker path),
safe optional-claim degradation, bounded evidence enrichment, source-health
gating, and the derived review queue. All fetches are canned FetchResults —
no network, no database.
"""

from __future__ import annotations

import pytest

from app.models.models import Scholarship, ScholarshipTrack
from scrapers.fetch_policy import (
    FetchResult,
    OUTCOME_ACCESS_DENIED,
    OUTCOME_OK,
    OUTCOME_PERMANENT_HTTP,
    OUTCOME_ROBOTS_UNAVAILABLE,
)
from scrapers.review import (
    ARCHIVED_SKIP,
    AUTO_RECHECK,
    BLOCKED_SOURCE,
    EVIDENCE_FETCH,
    FUND_TITLE_EVIDENCE,
    GENERIC_PROVIDER,
    HUMAN_REVIEW,
    NO_OPPORTUNITY_NOUN,
    SOURCE_UNVERIFIABLE,
    TITLE_ABSENT_ON_SOURCE,
    UNSUPPORTED_ANY,
    UNSUPPORTED_AWARD,
    UNSUPPORTED_DEADLINE,
    UNSUPPORTED_GPA,
    UNSUPPORTED_TITLE,
    _extract_from_row,
    classify_record,
    queue_category,
    reevaluate_record,
)
from scrapers.extraction import attach_verification, narrow_disciplines_to_evidence
from scrapers.schema import ScholarshipExtract

LISTING_URL = "https://cf.example.org/scholarships"
DETAIL_URL = "https://cf.example.org/scholarships/alpha"


def _vf(**kw):
    base = {
        "title": "verified", "award_amount": "not_asserted",
        "deadline": "not_asserted", "min_gpa": "not_asserted",
    }
    base.update(kw)
    return base


def _row(**kw) -> Scholarship:
    defaults = dict(
        title="Alpha Scholarship", provider="Example Foundation",
        portal_url=LISTING_URL, source_url=LISTING_URL,
        award_amount=None, deadline=None, min_gpa=0.0, max_sai=None,
        eligible_disciplines=[], eligible_credentials=[],
        is_general_major=False, verification_status="needs_review",
        verified_fields=_vf(), lifecycle_status="published",
        archive_reason=None, is_archived=False,
        extraction_method="llm", scope=None, estimated_next_cycle=None,
        last_checked_at=None, verified_at=None, is_local=False,
        competition_level="medium", funding_type=None,
        state_restrictions=[], metro_restrictions=[], county_restrictions=[],
        city_restrictions=[], academic_levels=[], required_affiliations=[],
        matching_tags=[], provider_core_values=[], enrollment_statuses=[],
        institution_restrictions=[], employment_required=False,
        has_service_commitment=False, consecutive_misses=0,
    )
    defaults.update(kw)
    return Scholarship(**defaults)


def _fetch(pages):
    """Canned fetch: url -> html string or FetchResult; missing -> 404."""

    async def _f(url: str) -> FetchResult:
        v = pages.get(url)
        if isinstance(v, FetchResult):
            return v
        if v is None:
            return FetchResult(url=url, outcome=OUTCOME_PERMANENT_HTTP,
                               http_status=404)
        return FetchResult(url=url, outcome=OUTCOME_OK, http_status=200, text=v)

    return _f


# ---------------------------------------------------------------------------
# Phase 1 — reason classification
# ---------------------------------------------------------------------------


class TestReasonClassification:
    def test_single_field_reason(self):
        row = _row(verified_fields=_vf(deadline="unverified"))
        reasons, checks = classify_record(row)
        assert reasons == [UNSUPPORTED_DEADLINE]
        assert checks == []

    def test_multiple_simultaneous_reasons(self):
        row = _row(
            eligible_disciplines=["any"],
            verified_fields=_vf(award_amount="unverified", deadline="unverified"),
        )
        reasons, _ = classify_record(row)
        assert set(reasons) == {
            UNSUPPORTED_AWARD, UNSUPPORTED_DEADLINE, UNSUPPORTED_ANY}

    def test_all_field_reasons(self):
        row = _row(verified_fields=_vf(
            title="unverified", award_amount="unverified",
            deadline="unverified", min_gpa="unverified"))
        reasons, _ = classify_record(row)
        assert reasons == [
            UNSUPPORTED_TITLE, UNSUPPORTED_AWARD,
            UNSUPPORTED_DEADLINE, UNSUPPORTED_GPA]

    def test_structural_reasons(self):
        row = _row(title="Career Services", provider="students")
        reasons, _ = classify_record(row)
        assert NO_OPPORTUNITY_NOUN in reasons
        assert GENERIC_PROVIDER in reasons

    def test_fund_title_is_evidence_check(self):
        row = _row(title="Harold Greene Memorial Fund")
        reasons, checks = classify_record(row)
        assert FUND_TITLE_EVIDENCE in checks
        assert FUND_TITLE_EVIDENCE not in reasons

    def test_empty_verified_fields(self):
        row = _row(verified_fields={})
        reasons, _ = classify_record(row)
        assert "no_persisted_evidence" in reasons


# ---------------------------------------------------------------------------
# Phase 4 — queue classification
# ---------------------------------------------------------------------------


class TestQueueClassification:
    def test_hard_reason_is_human(self):
        row = _row(title="Career Services")
        assert queue_category(row, [NO_OPPORTUNITY_NOUN], []) == HUMAN_REVIEW

    def test_blocked_health(self):
        row = _row()
        assert queue_category(
            row, [UNSUPPORTED_ANY], [],
            source_health="access_denied") == BLOCKED_SOURCE
        assert queue_category(
            row, [UNSUPPORTED_ANY], [],
            source_health="robots_unavailable") == BLOCKED_SOURCE

    def test_distinct_portal_is_evidence_fetch(self):
        row = _row(portal_url=DETAIL_URL)
        assert queue_category(row, [UNSUPPORTED_AWARD], []) == EVIDENCE_FETCH

    def test_same_page_is_auto_recheck(self):
        row = _row()
        assert queue_category(row, [UNSUPPORTED_ANY], []) == AUTO_RECHECK

    def test_archived_deadline_passed_skipped(self):
        row = _row(lifecycle_status="archived", archive_reason="deadline_passed")
        assert queue_category(row, [UNSUPPORTED_ANY], []) == ARCHIVED_SKIP


# ---------------------------------------------------------------------------
# Phase 2 — deterministic re-evaluation through the real engine
# ---------------------------------------------------------------------------


class TestReevaluation:
    @pytest.mark.asyncio
    async def test_clears_when_fresh_evidence_supports(self):
        row = _row(
            award_amount=5000,
            verified_fields=_vf(award_amount="unverified"))
        pages = {LISTING_URL:
                 "<html>Alpha Scholarship — award $5,000 annually to students.</html>"}
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert out.cleared
        assert row.verification_status == "verified"
        assert row.award_amount == 5000  # supported — kept, not degraded
        assert row.verified_fields["award_amount"] == "verified"

    @pytest.mark.asyncio
    async def test_degrades_unsupported_amount(self):
        row = _row(
            award_amount=5000,
            verified_fields=_vf(award_amount="unverified"))
        pages = {LISTING_URL: "<html>Alpha Scholarship for students.</html>"}
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert out.cleared
        assert UNSUPPORTED_AWARD in out.degraded
        assert row.award_amount is None
        assert row.verified_fields["award_amount"] == "not_asserted"
        assert row.verification_status == "verified"

    @pytest.mark.asyncio
    async def test_degrades_unrestricted_claim(self):
        row = _row(
            eligible_disciplines=["any"], is_general_major=True,
            verified_fields=_vf())
        pages = {LISTING_URL:
                 "<html>Alpha Scholarship. Application details vary.</html>"}
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert out.cleared
        assert UNSUPPORTED_ANY in out.degraded
        assert row.eligible_disciplines == []
        assert row.is_general_major is False
        assert row.verification_status == "verified"

    @pytest.mark.asyncio
    async def test_any_proven_by_evidence_kept(self):
        row = _row(
            eligible_disciplines=["any"], is_general_major=True,
            verified_fields=_vf())
        pages = {LISTING_URL:
                 "<html>Alpha Scholarship — open to students in all "
                 "fields of study.</html>"}
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert out.cleared
        assert not out.degraded
        assert row.eligible_disciplines == ["any"]

    @pytest.mark.asyncio
    async def test_pharmacy_subtree_rescope_preserved(self):
        """'all fields of pharmacy' rescopes to pharmacy — never 'any'."""
        row = _row(
            eligible_disciplines=["any"],
            verified_fields=_vf())
        pages = {LISTING_URL:
                 "<html>Alpha Scholarship — open to students in all "
                 "fields of pharmacy.</html>"}
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert out.cleared
        assert row.eligible_disciplines == ["pharmacy"]

    @pytest.mark.asyncio
    async def test_noop_when_title_absent(self):
        """An opportunity whose title is gone from its source cannot clear."""
        row = _row(verified_fields=_vf())
        pages = {LISTING_URL: "<html>Completely different program.</html>"}
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert not out.cleared
        assert out.action == "gated"
        assert out.queue == HUMAN_REVIEW
        assert TITLE_ABSENT_ON_SOURCE in out.reasons_after
        assert row.verification_status == "needs_review"

    @pytest.mark.asyncio
    async def test_title_unverified_never_degrades(self):
        row = _row(verified_fields=_vf(title="unverified"))
        pages = {LISTING_URL: "<html>Other content entirely.</html>"}
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert not out.cleared
        assert not out.degraded
        assert row.title == "Alpha Scholarship"  # identity never degraded

    @pytest.mark.asyncio
    async def test_deadline_year_guard_on_recheck(self):
        """A deadline whose year never appears in evidence is dropped —
        the same C1 rule extraction applies."""
        row = _row(
            deadline=__import__("datetime").date(2026, 3, 1),
            verified_fields=_vf(deadline="unverified"))
        pages = {LISTING_URL:
                 "<html>Alpha Scholarship — apply by March 1.</html>"}
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert out.cleared
        assert row.deadline is None

    @pytest.mark.asyncio
    async def test_min_gpa_degrades_to_not_asserted(self):
        row = _row(
            min_gpa=3.5,
            verified_fields=_vf(min_gpa="unverified"))
        pages = {LISTING_URL: "<html>Alpha Scholarship for students.</html>"}
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert out.cleared
        assert UNSUPPORTED_GPA in out.degraded
        assert row.min_gpa == 0.0  # persisted "not asserted" representation
        assert row.verified_fields["min_gpa"] == "not_asserted"


# ---------------------------------------------------------------------------
# Phase 3 — bounded evidence enrichment
# ---------------------------------------------------------------------------


class TestEvidenceEnrichment:
    @pytest.mark.asyncio
    async def test_detail_page_supplies_missing_fact(self):
        row = _row(
            portal_url=DETAIL_URL, award_amount=2500,
            verified_fields=_vf(award_amount="unverified"))
        pages = {
            LISTING_URL: "<html>Alpha Scholarship listed here.</html>",
            DETAIL_URL: "<html>Alpha Scholarship — grants $2,500.</html>",
        }
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert out.cleared
        assert not out.degraded
        assert row.award_amount == 2500
        assert set(out.evidence_urls) == {LISTING_URL, DETAIL_URL}

    @pytest.mark.asyncio
    async def test_degrades_only_after_evidence_exhausted(self):
        row = _row(
            portal_url=DETAIL_URL, award_amount=2500,
            verified_fields=_vf(award_amount="unverified"))
        pages = {
            LISTING_URL: "<html>Alpha Scholarship listed.</html>",
            DETAIL_URL: "<html>Alpha Scholarship — details here.</html>",
        }
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert out.cleared
        assert UNSUPPORTED_AWARD in out.degraded
        assert row.award_amount is None

    @pytest.mark.asyncio
    async def test_access_denied_stays_gated(self):
        row = _row(verified_fields=_vf(award_amount="unverified"))
        pages = {LISTING_URL: FetchResult(
            url=LISTING_URL, outcome=OUTCOME_ACCESS_DENIED, http_status=403)}
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert not out.cleared
        assert out.action == "blocked"
        assert out.queue == BLOCKED_SOURCE
        assert SOURCE_UNVERIFIABLE in out.reasons_after
        assert row.verification_status == "needs_review"

    @pytest.mark.asyncio
    async def test_robots_unavailable_stays_gated(self):
        row = _row(verified_fields=_vf())
        pages = {LISTING_URL: FetchResult(
            url=LISTING_URL, outcome=OUTCOME_ROBOTS_UNAVAILABLE)}
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert not out.cleared
        assert out.queue == BLOCKED_SOURCE
        assert row.verification_status == "needs_review"


# ---------------------------------------------------------------------------
# Listing scoping — a sibling's facts never verify this child (C5 rule)
# ---------------------------------------------------------------------------


class TestScopedEvidence:
    @pytest.mark.asyncio
    async def test_sibling_facts_do_not_leak(self):
        row = _row(
            title="Alpha Scholarship", award_amount=9000,
            verified_fields=_vf(award_amount="unverified"))
        page = ("<html><h2>Alpha Scholarship</h2><p>For students.</p>"
                "<h2>Beta Scholarship</h2><p>Award $9,000 deadline June 1, 2026.</p></html>")
        out = await reevaluate_record(
            row, fetch=_fetch({LISTING_URL: page}),
            sibling_titles=["Beta Scholarship"])
        # $9,000 exists only in Beta's segment — Alpha's claim stays
        # unsupported and degrades to unknown rather than adopting it.
        assert out.cleared
        assert UNSUPPORTED_AWARD in out.degraded
        assert row.award_amount is None

    @pytest.mark.asyncio
    async def test_own_segment_supports_facts(self):
        row = _row(
            title="Alpha Scholarship", award_amount=1500,
            verified_fields=_vf(award_amount="unverified"))
        page = ("<html><h2>Alpha Scholarship</h2><p>Award $1,500 to students.</p>"
                "<h2>Beta Scholarship</h2><p>Different award.</p></html>")
        out = await reevaluate_record(
            row, fetch=_fetch({LISTING_URL: page}),
            sibling_titles=["Beta Scholarship"])
        assert out.cleared
        assert not out.degraded
        assert row.award_amount == 1500


# ---------------------------------------------------------------------------
# Preserved trust rules
# ---------------------------------------------------------------------------


class TestTrustRulesPreserved:
    @pytest.mark.asyncio
    async def test_fund_title_gated_without_education_evidence(self):
        row = _row(title="Harold Greene Memorial Fund",
                   verified_fields=_vf())
        pages = {LISTING_URL:
                 "<html>Harold Greene Memorial Fund — established to benefit "
                 "the region. Grants to community causes.</html>"}
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert not out.cleared
        assert FUND_TITLE_EVIDENCE in out.reasons_after
        assert row.verification_status == "needs_review"

    @pytest.mark.asyncio
    async def test_fund_title_clears_with_education_evidence(self):
        row = _row(title="Brindle Family Scholarship Fund",
                   verified_fields=_vf())
        pages = {LISTING_URL:
                 "<html>Brindle Family Scholarship Fund provides annual "
                 "scholarships to students pursuing higher education.</html>"}
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert out.cleared

    @pytest.mark.asyncio
    async def test_no_opportunity_noun_stays_gated(self):
        row = _row(title="Career Services Portal",
                   verified_fields=_vf())
        pages = {LISTING_URL: "<html>Career Services Portal</html>"}
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert not out.cleared
        assert NO_OPPORTUNITY_NOUN in out.reasons_after

    @pytest.mark.asyncio
    async def test_archived_record_not_republished(self):
        """A cleared archived record gains verification, never republication —
        lifecycle transitions stay owned by app.services.lifecycle."""
        row = _row(lifecycle_status="archived", archive_reason="dead_link",
                   is_archived=True, verified_fields=_vf())
        pages = {LISTING_URL: "<html>Alpha Scholarship for students.</html>"}
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert out.cleared
        assert row.verification_status == "verified"
        assert row.lifecycle_status == "archived"
        assert row.is_archived is True

    @pytest.mark.asyncio
    async def test_tracks_untouched_by_clearance(self):
        row = _row(verified_fields=_vf())
        track = ScholarshipTrack(title="Nursing Track")
        row.tracks = [track]
        pages = {LISTING_URL: "<html>Alpha Scholarship for students.</html>"}
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert out.cleared
        assert row.tracks == [track]

    @pytest.mark.asyncio
    async def test_verified_fields_stay_field_verdict_contract(self):
        row = _row(
            award_amount=500, eligible_disciplines=["any"],
            verified_fields=_vf(award_amount="unverified"))
        pages = {LISTING_URL: "<html>Alpha Scholarship for students.</html>"}
        out = await reevaluate_record(row, fetch=_fetch(pages))
        assert out.cleared
        assert set(row.verified_fields) == {
            "title", "award_amount", "deadline", "min_gpa"}
        assert all(isinstance(v, str) for v in row.verified_fields.values())


# ---------------------------------------------------------------------------
# NASW / discipline over-breadth narrowing (generic, provider-agnostic)
# ---------------------------------------------------------------------------


class TestDisciplineNarrowing:
    def test_area_claim_narrows_to_curated_descendant(self):
        # The NASW defect class: the source registry declares social_work,
        # the record claimed its parent area — evidence names no other
        # social_sciences descendant, so the claim narrows.
        assert narrow_disciplines_to_evidence(
            ["social_sciences"],
            "award supports social work students",
            source_discipline="social_work") == ["social_work"]

    def test_no_source_hint_never_narrows(self):
        # Page-text pattern matching alone must never narrow — a partial
        # matcher cannot safely cover a genuinely broad program (IHS LRP
        # names only a few of the professions it funds).
        assert narrow_disciplines_to_evidence(
            ["social_sciences"], "social work students only") == \
            ["social_sciences"]

    def test_evidence_vetoes_genuine_breadth(self):
        # Engineering association hosting a true STEM award: the evidence
        # names other stem descendants, so 'stem' is honestly supported.
        assert narrow_disciplines_to_evidence(
            ["stem"],
            "engineering, computer science and mathematics majors",
            source_discipline="engineering") == ["stem"]

    def test_non_descendant_hint_never_rewrites(self):
        # Source declares nursing but the claim is social_sciences —
        # unrelated subtrees; a contradiction for review, not a rewrite.
        assert narrow_disciplines_to_evidence(
            ["social_sciences"], "nursing students only",
            source_discipline="nursing") == ["social_sciences"]

    def test_leaf_claims_untouched(self):
        assert narrow_disciplines_to_evidence(
            ["nursing"], "social work students",
            source_discipline="social_work") == ["nursing"]

    def test_any_claim_untouched(self):
        assert narrow_disciplines_to_evidence(
            ["any"], "social work students",
            source_discipline="social_work") == ["any"]

    def test_any_hint_never_proposes(self):
        # Sources declaring 'any' propose no narrowing — genuinely broad
        # programs (IHS LRP, Gilman) keep their honest broad claim.
        assert narrow_disciplines_to_evidence(
            ["health_professions"], "physicians and nurses",
            source_discipline="any") == ["health_professions"]

    def test_attach_verification_preserves_broad_claim(self):
        # attach_verification itself does not narrow — the correction needs
        # the curated source hint, which raw verification never sees.
        ex = ScholarshipExtract(
            title="Memorial Social Award", provider="Workers Foundation",
            eligible_disciplines=["social_sciences"])
        ex = attach_verification(
            ex, text="Memorial Social Award for social work students "
                     "pursuing a degree.", source_url="https://x.org/s")
        assert ex.eligible_disciplines == ["social_sciences"]

    @pytest.mark.asyncio
    async def test_reevaluation_narrows_overbroad_claim(self):
        row = _row(
            eligible_disciplines=["social_sciences"],
            verified_fields=_vf(deadline="unverified"),
            deadline=__import__("datetime").date(2026, 6, 1))
        pages = {LISTING_URL:
                 "<html>Alpha Scholarship for social work students — "
                 "apply by June 1, 2026.</html>"}
        out = await reevaluate_record(
            row, fetch=_fetch(pages), source_discipline="social_work")
        assert out.cleared
        assert row.eligible_disciplines == ["social_work"]

    @pytest.mark.asyncio
    async def test_reevaluation_evidence_veto_keeps_breadth(self):
        row = _row(
            eligible_disciplines=["stem"],
            verified_fields=_vf())
        pages = {LISTING_URL:
                 "<html>Alpha Scholarship for engineering, computer "
                 "science and mathematics majors.</html>"}
        out = await reevaluate_record(
            row, fetch=_fetch(pages), source_discipline="engineering")
        assert out.cleared
        assert row.eligible_disciplines == ["stem"]


# ---------------------------------------------------------------------------
# Rebuild-from-row mapping
# ---------------------------------------------------------------------------


class TestExtractRebuild:
    def test_min_gpa_zero_means_not_asserted(self):
        row = _row(min_gpa=0.0)
        assert _extract_from_row(row).min_gpa is None

    def test_deadline_iso_round_trip(self):
        import datetime as _dt

        row = _row(deadline=_dt.date(2026, 5, 1))
        assert _extract_from_row(row).deadline == "2026-05-01"

    def test_record_fields_survive_rebuild(self):
        row = _row(provider="P", portal_url="https://p.org/x",
                   award_amount=100, eligible_disciplines=["nursing"])
        ex = _extract_from_row(row)
        assert (ex.provider, ex.portal_url, ex.award_amount,
                ex.eligible_disciplines) == (
                    "P", "https://p.org/x", 100, ["nursing"])
