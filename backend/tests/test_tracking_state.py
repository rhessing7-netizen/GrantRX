"""Regression tests for Save/Dismiss state semantics (Phase 2 repairs).

P2-D1: POST /user-scholarships must be idempotent — a duplicate save returns
the existing tracking record instead of crashing on UNIQUE(user_id,
scholarship_id).

P2-D2: Dismissal is a discovery preference, not pipeline state. Rows created
solely by dismiss are marked dismiss_only, are excluded from the tracking
list (Kanban), and are deleted by undismiss instead of becoming phantom
"saved" records.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.main import app
from app.middleware.auth import DEMO_USER_ID
from app.models.models import Profile, Scholarship, UserScholarship


def _make_profile(**kwargs):
    defaults = {
        "id": DEMO_USER_ID, "subscription_tier": "free",
        "searches_used_this_week": 0, "search_cycle_reset_at": None,
        "disciplines": [], "target_credentials": [], "primary_discipline": None,
        "target_credential": None, "clinical_phase": None, "gpa": None,
        "state_residence": None, "metro_area": None, "sai_score": None,
        "first_gen": False, "minority_flag": False,
        "professional_affiliations": [], "hobbies": [],
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


_TRACKING_OUT_FIELDS = {
    "status": "saved",
    "custom_deadline_reminder": None,
    "user_notes": None,
    "application_notes": None,
    "documents": [],
    "checklist": [],
    "is_dismissed": False,
    "dismiss_only": False,
    "is_planned": False,
    "target_submission_date": None,
}


def _fill_orm_defaults(obj):
    """Populate the fields a real flush/refresh would set so the response
    model can serialize an ORM row created under a mocked session."""
    if getattr(obj, "id", None) is None:
        obj.id = uuid4()
    for k, v in _TRACKING_OUT_FIELDS.items():
        if getattr(obj, k, None) is None:
            setattr(obj, k, v)


def _make_tracking(**kwargs):
    defaults = {
        "id": uuid4(),
        "user_id": DEMO_USER_ID,
        "scholarship_id": uuid4(),
        "created_at": None,
        "updated_at": None,
        "scholarship": None,
    }
    defaults.update(_TRACKING_OUT_FIELDS)
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_db(*, profile=None, user_scholarship=None, scholarship=None,
             user_scholarship_list=None):
    db = MagicMock()
    db._query_map = {}

    def query_side_effect(arg):
        if arg in db._query_map:
            return db._query_map[arg]
        q = MagicMock()
        db._query_map[arg] = q
        if arg is Profile:
            q.filter.return_value.first.return_value = profile
        elif arg is Scholarship:
            q.filter.return_value.first.return_value = scholarship
        elif arg is UserScholarship:
            q.filter.return_value.first.return_value = user_scholarship
            q.filter.return_value.all.return_value = user_scholarship_list or []
        else:
            q.filter.return_value.all.return_value = []
            q.filter.return_value.count.return_value = 0
        return q

    db.query.side_effect = query_side_effect
    return db


@pytest.fixture(autouse=True)
def dev_env():
    with patch.dict(os.environ, {"ENVIRONMENT": "development"}):
        yield


@pytest.fixture
def client(authenticated_client_factory):
    yield authenticated_client_factory(app)
    app.dependency_overrides.clear()


def _override_db(db):
    app.dependency_overrides[get_db] = lambda: db


# ---------------------------------------------------------------------------
# P2-D1: idempotent save
# ---------------------------------------------------------------------------


class TestIdempotentSave:
    def test_first_save_creates_record(self, client):
        db = _make_db(profile=_make_profile(), user_scholarship=None)
        db.refresh.side_effect = _fill_orm_defaults
        _override_db(db)
        resp = client.post("/user-scholarships",
                           json={"scholarship_id": str(uuid4())})
        assert resp.status_code == 201
        db.add.assert_called_once()

    def test_duplicate_save_returns_existing_200(self, client):
        """Second save returns the existing record — no 500, no new row."""
        existing = _make_tracking()
        db = _make_db(profile=_make_profile(), user_scholarship=existing)
        _override_db(db)
        resp = client.post("/user-scholarships",
                           json={"scholarship_id": str(existing.scholarship_id)})
        assert resp.status_code == 200
        db.add.assert_not_called()

    def test_save_integrity_error_race_returns_existing(self, client):
        """Concurrent-insert race: UNIQUE violation -> refetch -> return row."""
        existing = _make_tracking()
        db = _make_db(profile=_make_profile())
        # Existence check sees nothing; refetch after rollback finds the row.
        q = MagicMock()
        q.filter.return_value.first.side_effect = [None, existing]
        q.filter.return_value.all.return_value = []
        q.filter.return_value.count.return_value = 0

        def query_side_effect(arg):
            if arg is Profile:
                pq = MagicMock()
                pq.filter.return_value.first.return_value = _make_profile()
                return pq
            return q

        db.query.side_effect = query_side_effect
        db.commit.side_effect = IntegrityError("INSERT", {}, Exception("unique"))
        _override_db(db)
        resp = client.post("/user-scholarships",
                           json={"scholarship_id": str(uuid4())})
        assert resp.status_code == 200
        db.rollback.assert_called_once()

    def test_save_promotes_dismiss_only_row(self, client):
        """Saving a dismissed-only opportunity converts it to real tracking."""
        existing = _make_tracking(dismiss_only=True, is_dismissed=True)
        db = _make_db(profile=_make_profile(), user_scholarship=existing)
        _override_db(db)
        resp = client.post("/user-scholarships",
                           json={"scholarship_id": str(existing.scholarship_id)})
        assert resp.status_code == 200
        assert existing.dismiss_only is False
        assert existing.is_dismissed is False
        assert existing.status.value == "saved"
        db.add.assert_not_called()


# ---------------------------------------------------------------------------
# P2-D2: dismiss ≠ save
# ---------------------------------------------------------------------------


class TestDismissOnly:
    def test_dismiss_untracked_creates_dismiss_only_row(self, client):
        scholarship = MagicMock()
        scholarship.id = uuid4()
        db = _make_db(profile=_make_profile(), user_scholarship=None,
                      scholarship=scholarship)
        _override_db(db)
        resp = client.post(f"/api/scholarships/{scholarship.id}/dismiss")
        assert resp.status_code == 200
        added = db.add.call_args[0][0]
        assert added.dismiss_only is True
        assert added.is_dismissed is True

    def test_dismiss_tracked_preserves_status(self, client):
        scholarship = MagicMock()
        scholarship.id = uuid4()
        existing = _make_tracking(status="in_progress", dismiss_only=False)
        db = _make_db(profile=_make_profile(), user_scholarship=existing,
                      scholarship=scholarship)
        _override_db(db)
        resp = client.post(f"/api/scholarships/{scholarship.id}/dismiss")
        assert resp.status_code == 200
        assert existing.is_dismissed is True
        assert existing.status == "in_progress"
        db.add.assert_not_called()

    def test_undismiss_deletes_dismiss_only_row(self, client):
        """Undo removes the dismiss-only row — no phantom Saved record."""
        existing = _make_tracking(dismiss_only=True, is_dismissed=True)
        db = _make_db(profile=_make_profile(), user_scholarship=existing)
        _override_db(db)
        resp = client.post(f"/api/scholarships/{uuid4()}/undismiss")
        assert resp.status_code == 200
        assert resp.json()["status"] == "restored"
        db.delete.assert_called_once_with(existing)

    def test_undismiss_real_row_clears_flag_only(self, client):
        existing = _make_tracking(dismiss_only=False, is_dismissed=True,
                                  status="submitted")
        db = _make_db(profile=_make_profile(), user_scholarship=existing)
        _override_db(db)
        resp = client.post(f"/api/scholarships/{uuid4()}/undismiss")
        assert resp.status_code == 200
        db.delete.assert_not_called()
        assert existing.is_dismissed is False
        assert existing.status == "submitted"

    def test_tracking_list_filters_dismiss_only(self, client):
        """GET /user-scholarships must exclude dismiss_only rows."""
        db = _make_db(profile=_make_profile(), user_scholarship_list=[])
        _override_db(db)
        resp = client.get("/user-scholarships")
        assert resp.status_code == 200
        # The endpoint chains .options(joinedload(...)).filter(...) — inspect
        # the filter args on the options() return value for dismiss_only.
        q = db._query_map[UserScholarship]
        joined_q = q.options.return_value
        filter_exprs = [str(c) for call in joined_q.filter.call_args_list
                        for c in call.args]
        assert any("dismiss_only" in e for e in filter_exprs)


# ---------------------------------------------------------------------------
# P2-F1: provenance exposure & trust boundary
# ---------------------------------------------------------------------------


class TestProvenance:
    def test_scholarship_out_exposes_provenance(self):
        from app.models.models import Scholarship
        from app.schemas.schemas import ScholarshipOut
        s = Scholarship(
            id=uuid4(), title="X", provider="Y", portal_url="https://x.test",
            award_amount=None, deadline=None, eligible_disciplines=[],
            eligible_credentials=[], min_gpa=0.0, max_sai=None,
            state_restrictions=[], metro_restrictions=[],
            required_affiliations=[], matching_tags=[], is_archived=False,
            academic_levels=[], county_restrictions=[], city_restrictions=[],
            provider_core_values=[], is_general_major=False, scope="national",
            is_local=False, competition_level="medium",
            funding_type="scholarship", employment_required=False,
            has_service_commitment=False,
            source_url="https://provider.test/page",
            extraction_method="deterministic", verification_status="verified",
            verified_fields={"title": "verified", "award_amount": "verified"},
            verified_at=None,
        )
        out = ScholarshipOut.model_validate(s)
        assert out.source_url == "https://provider.test/page"
        assert out.verification_status == "verified"
        assert out.verified_fields["title"] == "verified"

    def test_scholarship_create_cannot_set_verification(self):
        """Client input must not be able to assert verification state."""
        from app.schemas.schemas import ScholarshipCreate
        payload = {
            "title": "X", "provider": "Y", "portal_url": "https://x.test",
            "verification_status": "verified",
        }
        obj = ScholarshipCreate(**payload)
        assert not hasattr(obj, "verification_status") or \
            "verification_status" not in obj.model_fields_set

    def test_extractor_cannot_self_certify(self):
        """_attach_source_verification derives status from source evidence —
        a pre-set 'verified' value on the extract is overwritten by the
        independent verifier."""
        from scrapers.runner import _attach_source_verification
        from scrapers.schema import ScholarshipExtract
        e = ScholarshipExtract(title="Missing From Page", provider="P",
                               portal_url="https://p.test", award_amount=5000)
        object.__setattr__(e, "verification_status", "verified")
        out = _attach_source_verification(e, "<html><body>empty</body></html>",
                                          "https://p.test/src")
        assert out.verification_status == "needs_review"
        assert out.verified_at is None

    def test_extractor_verified_when_evidence_present(self):
        from scrapers.runner import _attach_source_verification
        from scrapers.schema import ScholarshipExtract
        html = "<html><body>Merit Grant $5,000 deadline December 1, 2027</body></html>"
        e = ScholarshipExtract(title="Merit Grant", provider="P",
                               portal_url="https://p.test", award_amount=5000,
                               deadline="2027-12-01")
        out = _attach_source_verification(e, html, "https://p.test/src")
        assert out.verification_status == "verified"
        assert out.verified_fields["title"] == "verified"
        assert out.verified_at is not None

    def test_matched_feed_includes_verification_status(self, client):
        from datetime import date, timedelta
        s = MagicMock()
        s.id = uuid4()
        s.title = "Verified Grant"
        s.provider = "P"
        s.portal_url = "https://p.test"
        s.award_amount = 100
        s.deadline = date.today() + timedelta(days=10)
        s.eligible_disciplines = []
        s.eligible_credentials = []
        s.min_gpa = 0.0
        s.max_sai = None
        s.state_restrictions = []
        s.metro_restrictions = []
        s.required_affiliations = []
        s.matching_tags = []
        s.is_archived = False
        s.estimated_next_cycle = None
        s.is_general_major = False
        s.academic_levels = []
        s.county_restrictions = []
        s.funding_type = "scholarship"
        s.employment_required = False
        s.has_service_commitment = False
        s.annual_benefit_cap = None
        s.vendor_platform = None
        s.provider_mission = None
        s.provider_core_values = []
        s.verification_status = "verified"
        prof = _make_profile(subscription_tier="premium")
        db = _make_db(profile=prof, user_scholarship=None)
        q_us = db.query.side_effect

        def query_side_effect(arg):
            q = MagicMock()
            if arg is Profile:
                q.filter.return_value.first.return_value = prof
            elif arg is Scholarship:
                q.all.return_value = [s]
            elif arg is UserScholarship:
                q.filter.return_value.all.return_value = []
            else:
                q.filter.return_value.all.return_value = []
            return q

        db.query.side_effect = query_side_effect
        _override_db(db)
        resp = client.get("/api/scholarships/matched")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert results[0]["verification_status"] == "verified"


# ---------------------------------------------------------------------------
# Final-E2E: the free-tier active-application cap must also apply when an
# EXISTING row transitions into an active status via POST re-save (e.g. a
# dismiss_only row converted with status=in_progress). Previously the
# early "return existing" path skipped the check entirely, bypassing PATCH
# enforcement.
# ---------------------------------------------------------------------------


class TestResaveActiveLimit:
    def test_resave_dismiss_only_to_active_blocked_at_cap(self, client):
        existing = _make_tracking(
            status="saved", dismiss_only=True, is_dismissed=True)
        db = _make_db(profile=_make_profile(), user_scholarship=existing)
        db.query(UserScholarship).filter.return_value.count.return_value = 3
        _override_db(db)
        resp = client.post("/user-scholarships", json={
            "scholarship_id": str(existing.scholarship_id),
            "status": "in_progress",
        })
        assert resp.status_code == 402
        detail = resp.json()["detail"]
        assert detail["detail"] == "PAYWALL_REQUIRED"

    def test_resave_dismiss_only_to_active_allowed_below_cap(self, client):
        existing = _make_tracking(
            status="saved", dismiss_only=True, is_dismissed=True)
        db = _make_db(profile=_make_profile(), user_scholarship=existing)
        db.query(UserScholarship).filter.return_value.count.return_value = 2
        _override_db(db)
        resp = client.post("/user-scholarships", json={
            "scholarship_id": str(existing.scholarship_id),
            "status": "in_progress",
        })
        assert resp.status_code == 200
        assert existing.status.value == "in_progress"
        assert existing.dismiss_only is False

    def test_resave_dismiss_only_to_saved_never_blocked(self, client):
        """Re-saving as 'saved' is a non-active transition — always allowed."""
        existing = _make_tracking(
            status="saved", dismiss_only=True, is_dismissed=True)
        db = _make_db(profile=_make_profile(), user_scholarship=existing)
        db.query(UserScholarship).filter.return_value.count.return_value = 3
        _override_db(db)
        resp = client.post("/user-scholarships", json={
            "scholarship_id": str(existing.scholarship_id),
        })
        assert resp.status_code == 200

    def test_resave_active_row_to_active_not_blocked(self, client):
        """An already-active row re-saved as active doesn't double-count."""
        existing = _make_tracking(
            status="in_progress", dismiss_only=True, is_dismissed=True)
        db = _make_db(profile=_make_profile(), user_scholarship=existing)
        db.query(UserScholarship).filter.return_value.count.return_value = 3
        _override_db(db)
        resp = client.post("/user-scholarships", json={
            "scholarship_id": str(existing.scholarship_id),
            "status": "in_progress",
        })
        assert resp.status_code == 200

    def test_resave_to_active_premium_never_blocked(self, client):
        existing = _make_tracking(
            status="saved", dismiss_only=True, is_dismissed=True)
        db = _make_db(
            profile=_make_profile(subscription_tier="premium"),
            user_scholarship=existing)
        db.query(UserScholarship).filter.return_value.count.return_value = 99
        _override_db(db)
        resp = client.post("/user-scholarships", json={
            "scholarship_id": str(existing.scholarship_id),
            "status": "submitted",
        })
        assert resp.status_code == 200
