"""C3 opportunity lifecycle foundation regression tests.

Covers lifecycle transitions, observation semantics, archive reasons,
dead-link resurrection prevention, annual-cycle recovery, shared portal-URL
safety rules, deadline archival, and discovery gating.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.models import Scholarship
from app.services import lifecycle
from app.services.archiver import apply_staleness_policy, archive_expired_scholarships
from scrapers.schema import ScholarshipExtract

TODAY = date.today()
FUTURE = TODAY + timedelta(days=60)
PAST = TODAY - timedelta(days=10)


def _row(**kw) -> Scholarship:
    defaults = dict(
        title="C3 Award", provider="C3 Provider",
        portal_url="https://c3.example.org/scholarships/c3-award",
        deadline=FUTURE, lifecycle_status="published", archive_reason=None,
        is_archived=False, consecutive_misses=0,
    )
    defaults.update(kw)
    return Scholarship(**defaults)


# ---------------------------------------------------------------------------
# Initial state + observation
# ---------------------------------------------------------------------------

class TestInitialAndObservation:
    def test_new_future_deadline_publishes_and_observes(self):
        s = Scholarship(title="t", provider="p", portal_url="u", deadline=FUTURE)
        lifecycle.initialize_new(s)
        assert s.lifecycle_status == "published"
        assert s.is_archived is False
        assert s.last_seen_at is not None and s.last_checked_at == s.last_seen_at
        assert s.consecutive_misses == 0

    def test_new_null_deadline_publishes_without_fabricating_deadline(self):
        s = Scholarship(title="t", provider="p", portal_url="u", deadline=None)
        lifecycle.initialize_new(s)
        assert s.lifecycle_status == "published"
        assert s.deadline is None

    def test_new_past_deadline_archives_with_reason(self):
        s = Scholarship(title="t", provider="p", portal_url="u", deadline=PAST)
        lifecycle.initialize_new(s)
        assert (s.lifecycle_status, s.archive_reason, s.is_archived) == ("archived", "deadline_passed", True)
        assert s.estimated_next_cycle is not None

    def test_observation_resets_misses(self):
        s = _row(consecutive_misses=4)
        lifecycle.record_observation(s)
        assert s.consecutive_misses == 0
        assert s.last_seen_at is not None

    def test_link_check_is_not_an_observation(self):
        s = _row(last_seen_at=None)
        lifecycle.record_check(s)
        assert s.last_checked_at is not None
        assert s.last_seen_at is None
        assert s.consecutive_misses == 0

    def test_no_miss_signal_is_manufactured_by_refresh_or_check(self):
        s = _row(consecutive_misses=0)
        lifecycle.record_check(s)
        lifecycle.apply_refresh(s, destination_verified=False)
        assert s.consecutive_misses == 0

    def test_invalid_archive_reason_rejected(self):
        with pytest.raises(ValueError):
            lifecycle.archive(_row(), "because")


# ---------------------------------------------------------------------------
# Refresh transitions
# ---------------------------------------------------------------------------

class TestRefreshTransitions:
    def test_published_stays_published(self):
        s = _row()
        lifecycle.apply_refresh(s, destination_verified=False)
        assert s.lifecycle_status == "published"

    def test_published_past_deadline_archives(self):
        s = _row(deadline=PAST)
        lifecycle.apply_refresh(s, destination_verified=True)
        assert (s.lifecycle_status, s.archive_reason) == ("archived", "deadline_passed")

    def test_stale_republishes_on_observation(self):
        s = _row(lifecycle_status="stale")
        lifecycle.apply_refresh(s, destination_verified=False)
        assert s.lifecycle_status == "published"

    def test_draft_is_not_auto_published(self):
        s = _row(lifecycle_status="draft")
        lifecycle.apply_refresh(s, destination_verified=True)
        assert s.lifecycle_status == "draft"

    # --- dead-link resurrection prevention ---
    @pytest.mark.parametrize("deadline", [None, FUTURE])
    def test_dead_link_not_resurrected_without_destination_evidence(self, deadline):
        s = _row(lifecycle_status="archived", archive_reason="dead_link", is_archived=True, deadline=deadline)
        lifecycle.apply_refresh(s, destination_verified=False)
        assert (s.lifecycle_status, s.archive_reason, s.is_archived) == ("archived", "dead_link", True)

    def test_dead_link_recovers_with_destination_evidence(self):
        s = _row(lifecycle_status="archived", archive_reason="dead_link", is_archived=True, deadline=None)
        lifecycle.apply_refresh(s, destination_verified=True)
        assert (s.lifecycle_status, s.archive_reason, s.is_archived) == ("published", None, False)

    def test_dead_link_with_past_deadline_stays_archived(self):
        s = _row(lifecycle_status="archived", archive_reason="dead_link", is_archived=True, deadline=PAST)
        lifecycle.apply_refresh(s, destination_verified=True)
        assert s.lifecycle_status == "archived"

    # --- annual-cycle recovery ---
    def test_deadline_archive_recovers_with_new_future_deadline(self):
        s = _row(lifecycle_status="archived", archive_reason="deadline_passed", is_archived=True, deadline=FUTURE)
        lifecycle.apply_refresh(s, destination_verified=False)
        assert s.lifecycle_status == "published"

    def test_deadline_archive_not_recovered_by_null_deadline(self):
        s = _row(lifecycle_status="archived", archive_reason="deadline_passed", is_archived=True, deadline=None)
        lifecycle.apply_refresh(s, destination_verified=True)
        assert (s.lifecycle_status, s.archive_reason) == ("archived", "deadline_passed")

    def test_deadline_archive_not_recovered_by_still_past_deadline(self):
        s = _row(lifecycle_status="archived", archive_reason="deadline_passed", is_archived=True, deadline=PAST)
        lifecycle.apply_refresh(s, destination_verified=True)
        assert s.lifecycle_status == "archived"

    @pytest.mark.parametrize("reason", ["manual", "discontinued", "duplicate", "source_removed"])
    def test_sticky_reasons_never_auto_reversed(self, reason):
        s = _row(lifecycle_status="archived", archive_reason=reason, is_archived=True, deadline=FUTURE)
        lifecycle.apply_refresh(s, destination_verified=True)
        assert (s.lifecycle_status, s.archive_reason) == ("archived", reason)


# ---------------------------------------------------------------------------
# upsert_scholarship integrates lifecycle (no resurrection via field refresh)
# ---------------------------------------------------------------------------

class TestUpsertLifecycle:
    def _upsert(self, existing, extract, destination_verified):
        from scrapers.runner import upsert_scholarship

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [existing]
        return upsert_scholarship(db, extract, destination_verified=destination_verified)

    def _extract(self, deadline=None):
        return ScholarshipExtract(
            title="C3 Award", provider="C3 Provider",
            portal_url="https://c3.example.org/scholarships/c3-award",
            deadline=deadline.isoformat() if deadline else None,
        )

    def test_refresh_does_not_resurrect_dead_link(self):
        existing = _row(lifecycle_status="archived", archive_reason="dead_link", is_archived=True, deadline=None)
        self._upsert(existing, self._extract(None), destination_verified=False)
        assert (existing.lifecycle_status, existing.is_archived) == ("archived", True)
        assert existing.last_seen_at is not None  # still an observation

    def test_refresh_new_cycle_republishes_deadline_archive(self):
        existing = _row(lifecycle_status="archived", archive_reason="deadline_passed", is_archived=True, deadline=PAST)
        self._upsert(existing, self._extract(FUTURE), destination_verified=False)
        assert existing.lifecycle_status == "published"
        assert existing.deadline == FUTURE

    def test_create_initializes_lifecycle(self):
        from scrapers.runner import upsert_scholarship

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        model, action = upsert_scholarship(db, self._extract(None))
        assert action == "created"
        assert model.lifecycle_status == "published"
        assert model.last_seen_at is not None


# ---------------------------------------------------------------------------
# Portal-URL fallback (runner) — shared opportunity-specific rule
# ---------------------------------------------------------------------------

class TestPortalFallback:
    def _run(self, portal, source, live):
        import scrapers.runner as runner
        from scrapers.fetch_policy import FetchResult

        async def _fake_check(url, **kw):
            ok = url in live
            return FetchResult(url=url, outcome="ok" if ok else "permanent_http",
                               http_status=200 if ok else 404)

        with patch.object(runner, "_check_url_result", _fake_check):
            url, ok, _decisive = asyncio.run(runner._verify_portal_url(portal, source))
            return url, ok

    def test_dead_portal_specific_same_site_source_accepted(self):
        url, ok = self._run(
            "https://c3.example.org/apply/closed-form",
            "https://c3.example.org/scholarships/c3-award",
            live={"https://c3.example.org/scholarships/c3-award"},
        )
        assert ok is True and url == "https://c3.example.org/scholarships/c3-award"

    def test_dead_portal_generic_homepage_rejected(self):
        url, ok = self._run(
            "https://c3.example.org/apply/closed-form",
            "https://c3.example.org/",
            live={"https://c3.example.org/"},
        )
        assert ok is False

    def test_dead_portal_unrelated_site_rejected(self):
        url, ok = self._run(
            "https://c3.example.org/apply/closed-form",
            "https://other-org.example.com/scholarships/list",
            live={"https://other-org.example.com/scholarships/list"},
        )
        assert ok is False

    def test_live_portal_passes_through(self):
        url, ok = self._run(
            "https://c3.example.org/apply",
            "https://c3.example.org/",
            live={"https://c3.example.org/apply"},
        )
        assert ok is True and url == "https://c3.example.org/apply"


# ---------------------------------------------------------------------------
# Dead-link repair job
# ---------------------------------------------------------------------------

class TestRepairOne:
    def _run(self, s, source_map, live):
        import scripts.repair_urls as ru

        async def _fake_check(url):
            return 200 if url in live else 404

        with patch.object(ru, "_check_url", _fake_check):
            return asyncio.run(ru.repair_one(s, source_map))

    def test_live_portal_is_check_not_observation(self):
        s = _row(last_seen_at=None)
        action = self._run(s, {}, live={s.portal_url})
        assert action == "ok"
        assert s.last_checked_at is not None and s.last_seen_at is None

    def test_dead_portal_specific_program_page_repairs(self):
        s = _row(portal_url="https://c3.example.org/apply/old", provider="C3 Provider")
        replacement = "https://c3.example.org/scholarships/c3-award"
        action = self._run(s, {"c3 provider": replacement}, live={replacement})
        assert action == "repaired"
        assert s.portal_url == replacement
        assert s.lifecycle_status == "published"

    def test_dead_portal_homepage_archives_dead_link(self):
        s = _row(portal_url="https://c3.example.org/apply/old", provider="C3 Provider")
        action = self._run(s, {"c3 provider": "https://c3.example.org/"}, live={"https://c3.example.org/"})
        assert action == "archived"
        assert (s.lifecycle_status, s.archive_reason, s.is_archived) == ("archived", "dead_link", True)

    def test_dead_portal_unrelated_provider_page_archives(self):
        s = _row(portal_url="https://c3.example.org/apply/old", provider="Foundation")
        unrelated = "https://unrelated-foundation.example.com/scholarships"
        action = self._run(s, {"community foundation": unrelated}, live={unrelated})
        assert action == "archived"
        assert s.archive_reason == "dead_link"


# ---------------------------------------------------------------------------
# Deadline archival + staleness policy
# ---------------------------------------------------------------------------

class TestArchiverAndStaleness:
    def test_deadline_archival_records_reason(self):
        s = _row(deadline=PAST)
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [s]
        assert archive_expired_scholarships(db) == 1
        assert (s.lifecycle_status, s.archive_reason, s.is_archived) == ("archived", "deadline_passed", True)

    def test_staleness_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("CATALOG_STALENESS_ENABLED", raising=False)
        assert apply_staleness_policy(MagicMock()) == 0

    def test_never_observed_rows_are_not_staled(self):
        policy = lifecycle.StalenessPolicy(enabled=True, max_days_unseen=1)
        s = _row(last_seen_at=None)
        assert lifecycle.apply_staleness(s, policy) is False
        assert s.lifecycle_status == "published"

    def test_old_observation_goes_stale(self):
        policy = lifecycle.StalenessPolicy(enabled=True, max_days_unseen=30)
        s = _row(last_seen_at=datetime.now(timezone.utc) - timedelta(days=31))
        assert lifecycle.apply_staleness(s, policy) is True
        assert (s.lifecycle_status, s.is_archived) == ("stale", False)

    def test_reliable_misses_threshold_goes_stale(self):
        policy = lifecycle.StalenessPolicy(enabled=True, max_consecutive_misses=2)
        s = _row(last_seen_at=datetime.now(timezone.utc))
        lifecycle.record_miss(s)
        lifecycle.record_miss(s)
        assert lifecycle.apply_staleness(s, policy) is True


# ---------------------------------------------------------------------------
# Discovery gating (lifecycle, not verification)
# ---------------------------------------------------------------------------

class TestDiscoveryGating:
    @pytest.mark.parametrize("status,visible", [
        ("published", True), ("draft", False), ("stale", False), ("archived", False),
    ])
    def test_is_discoverable(self, status, visible):
        reason = "manual" if status == "archived" else None
        assert lifecycle.is_discoverable(_row(lifecycle_status=status, archive_reason=reason)) is visible

    def test_pending_verification_visibility_policy(self):
        """E1.5 owner decision: needs_review is persisted but excluded from
        consumer discovery; legacy_unverified remains discoverable."""
        assert lifecycle.is_discoverable(_row(verification_status="needs_review")) is False
        assert lifecycle.is_discoverable(_row(verification_status="legacy_unverified")) is True

    def test_matcher_excludes_non_published(self):
        from app.services.matcher import match_scholarships

        profile = MagicMock()
        for k, v in dict(disciplines=[], target_credentials=[], primary_discipline=None,
                         target_credential=None, clinical_phase=None, gpa=None,
                         state_residence=None, metro_area=None, sai_score=None,
                         first_gen=False, minority_flag=False,
                         professional_affiliations=[], hobbies=[],
                         subscription_tier="premium").items():
            setattr(profile, k, v)

        rows = []
        for status in ("published", "draft", "stale", "archived"):
            rows.append(_row(
                title=f"C3 {status}", lifecycle_status=status,
                archive_reason="manual" if status == "archived" else None,
                eligible_disciplines=[], eligible_credentials=[], min_gpa=0.0,
                state_restrictions=[], metro_restrictions=[], required_affiliations=[],
                matching_tags=[], academic_levels=[], county_restrictions=[],
                city_restrictions=[], provider_core_values=[], scope="national",
                verified_fields={}, verification_status="legacy_unverified",
            ))
        titles = {r.title for r in match_scholarships(profile, rows)}
        assert titles == {"C3 published"}

    def test_legacy_objects_without_lifecycle_fall_back_to_is_archived(self):
        s = MagicMock()
        s.lifecycle_status = None
        s.is_archived = True
        assert lifecycle.is_discoverable(s) is False
        s.is_archived = False
        assert lifecycle.is_discoverable(s) is True
