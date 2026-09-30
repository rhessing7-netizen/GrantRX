"""Tests for the R3 early-access / waitlist signup endpoint.

Covers the contract in the implementation brief:
  - valid signup persists a durable lead (DB-first)
  - validation: bad email, bad audience/education values, missing consent,
    input bounds
  - email normalization + duplicate-safe signup
  - first-touch attribution preservation on resubmission
  - provider success / provider failure / provider unconfigured — a provider
    problem after a successful commit can never lose the lead
  - no provider credential leakage to the client
  - rate limiting
  - lead -> account conversion marking on profile creation
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app, early_access_rate_limiter
from app.middleware.auth import DEMO_USER_ID
from app.models.models import Profile, WaitlistLead
from app.schemas.schemas import WaitlistAudienceType
from app.services.email_marketing import (
    EmailOctopusProvider,
    ProviderSyncResult,
    waitlist_tags_for_audience,
)


# ---------------------------------------------------------------------------
# Model-aware fake session
# ---------------------------------------------------------------------------


def _eval_criterion(criterion, row) -> bool:
    """Evaluate the ``col == value`` criteria the endpoint emits."""
    clauses = getattr(criterion, "clauses", None)
    if clauses is not None:
        return all(_eval_criterion(c, row) for c in clauses)
    left = getattr(criterion.left, "key", None) or getattr(criterion.left, "name", None)
    right = criterion.right
    rval = getattr(right, "value", right)
    opname = getattr(criterion.operator, "__name__", str(criterion.operator))
    if opname == "eq":
        return getattr(row, left) == rval
    raise AssertionError(f"FakeWaitlistSession does not support operator {opname!r}")


class _WaitlistQuery:
    def __init__(self, session, model):
        self._rows = list(session._rows.get(model, []))

    def filter(self, *criteria):
        self._rows = [r for r in self._rows if all(_eval_criterion(c, r) for c in criteria)]
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class FakeWaitlistSession:
    """Session fake keyed by model so Profile and WaitlistLead lookups stay
    distinct (unlike a bare MagicMock or a model-blind row list)."""

    def __init__(self, leads=None, profiles=None):
        self._rows = {
            WaitlistLead: list(leads or []),
            Profile: list(profiles or []),
        }
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.commit_errors = []

    def query(self, model):
        return _WaitlistQuery(self, model)

    def add(self, obj):
        self._rows.setdefault(type(obj), []).append(obj)
        self.added.append(obj)

    def commit(self):
        if self.commit_errors:
            raise self.commit_errors.pop(0)
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, obj):
        """Materialize column defaults like a real flush + refresh would, so
        response serialization sees the same values Postgres would return."""
        for col in obj.__table__.columns:
            if getattr(obj, col.name) is None and col.default is not None:
                default = col.default.arg
                if not callable(default):
                    setattr(obj, col.name, default)
                    continue
                # ColumnDefault wraps callables to take a ctx argument.
                try:
                    setattr(obj, col.name, default(None))
                except TypeError:
                    setattr(obj, col.name, default())

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def prod_env():
    """Production mode: the public endpoint must work with no auth header."""
    with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
        yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    early_access_rate_limiter.reset()
    yield
    early_access_rate_limiter.reset()


@pytest.fixture(autouse=True)
def _no_provider_env():
    """Default: EmailOctopus unconfigured — sync must be marked skipped."""
    with patch.dict(
        os.environ, {"EMAILOCTOPUS_API_KEY": "", "EMAILOCTOPUS_LIST_ID": ""}
    ):
        yield


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def _override_db(db):
    app.dependency_overrides[get_db] = lambda: db


def _payload(**overrides):
    base = {
        "first_name": "Jamie",
        "email": "jamie@example.com",
        "audience_type": "student",
        "education_type": "undergraduate",
        "consent": True,
    }
    base.update(overrides)
    return base


def _existing_lead(**overrides):
    base = dict(
        id=uuid4(),
        email="jamie@example.com",
        first_name="Jamie",
        audience_type="student",
        education_type="undergraduate",
        status="waitlist",
        referral_source="themissrubie",
        referral_code=None,
        referred_by=None,
        utm_source="newsletter",
        utm_medium=None,
        utm_campaign="launch",
        utm_content=None,
        utm_term=None,
        landing_page="/early-access",
        consent_timestamp=datetime.now(timezone.utc) - timedelta(days=7),
        consent_source="early_access_form",
        provider_sync_status="synced",
        provider_synced_at=datetime.now(timezone.utc) - timedelta(days=7),
        provider_last_error=None,
        converted_to_user=False,
        converted_at=None,
        converted_user_id=None,
        created_at=datetime.now(timezone.utc) - timedelta(days=7),
        updated_at=datetime.now(timezone.utc) - timedelta(days=7),
    )
    base.update(overrides)
    lead = WaitlistLead()
    for k, v in base.items():
        setattr(lead, k, v)
    return lead


# ===========================================================================
# Valid signup + persistence
# ===========================================================================


class TestEarlyAccessSignup:
    def test_valid_signup_persists_lead(self, client):
        db = FakeWaitlistSession()
        _override_db(db)

        resp = client.post(
            "/api/v1/early-access",
            json=_payload(
                referral_source="creator",
                utm_source="instagram",
                utm_campaign="prelaunch",
                landing_page="/early-access",
            ),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "ok"
        assert body["already_registered"] is False

        assert len(db.added) == 1
        lead = db.added[0]
        assert lead.email == "jamie@example.com"
        assert lead.first_name == "Jamie"
        assert lead.audience_type == "student"
        assert lead.education_type == "undergraduate"
        assert lead.status == "waitlist"
        assert lead.referral_source == "creator"
        assert lead.utm_source == "instagram"
        assert lead.utm_campaign == "prelaunch"
        assert lead.landing_page == "/early-access"
        assert lead.consent_timestamp is not None
        assert lead.consent_source == "early_access_form"
        # Provider unconfigured -> sync skipped, lead still durable.
        assert lead.provider_sync_status == "skipped"
        assert lead.converted_to_user is False

    def test_public_without_auth_header(self, client):
        """No Authorization header must not yield 401 — this is pre-account."""
        _override_db(FakeWaitlistSession())
        resp = client.post("/api/v1/early-access", json=_payload())
        assert resp.status_code == 201

    def test_email_normalized(self, client):
        db = FakeWaitlistSession()
        _override_db(db)
        resp = client.post(
            "/api/v1/early-access",
            json=_payload(email="  Jamie.Smith+News@Example.COM "),
        )
        assert resp.status_code == 201
        assert db.added[0].email == "jamie.smith+news@example.com"

    def test_first_name_control_chars_stripped(self, client):
        db = FakeWaitlistSession()
        _override_db(db)
        resp = client.post(
            "/api/v1/early-access",
            json=_payload(first_name="  Jami\x00e  "),
        )
        assert resp.status_code == 201
        assert db.added[0].first_name == "Jamie"


# ===========================================================================
# Validation
# ===========================================================================


class TestEarlyAccessValidation:
    @pytest.mark.parametrize("email", ["not-an-email", "a@b", "a b@c.com", "@x.com"])
    def test_invalid_email_rejected(self, client, email):
        _override_db(FakeWaitlistSession())
        resp = client.post("/api/v1/early-access", json=_payload(email=email))
        assert resp.status_code == 422

    def test_invalid_audience_type_rejected(self, client):
        _override_db(FakeWaitlistSession())
        resp = client.post(
            "/api/v1/early-access", json=_payload(audience_type="wizard")
        )
        assert resp.status_code == 422

    def test_invalid_education_type_rejected(self, client):
        _override_db(FakeWaitlistSession())
        resp = client.post(
            "/api/v1/early-access", json=_payload(education_type="kindergarten")
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("consent", [False, None])
    def test_missing_or_false_consent_rejected(self, client, consent):
        _override_db(FakeWaitlistSession())
        payload = _payload()
        if consent is None:
            payload.pop("consent")
        else:
            payload["consent"] = consent
        resp = client.post("/api/v1/early-access", json=payload)
        assert resp.status_code == 422

    @pytest.mark.parametrize("audience", [a.value for a in WaitlistAudienceType])
    def test_all_audience_values_accepted(self, client, audience):
        _override_db(FakeWaitlistSession())
        resp = client.post(
            "/api/v1/early-access", json=_payload(audience_type=audience)
        )
        assert resp.status_code == 201

    def test_oversized_first_name_rejected(self, client):
        _override_db(FakeWaitlistSession())
        resp = client.post(
            "/api/v1/early-access", json=_payload(first_name="J" * 81)
        )
        assert resp.status_code == 422

    def test_oversized_attribution_rejected(self, client):
        _override_db(FakeWaitlistSession())
        resp = client.post(
            "/api/v1/early-access", json=_payload(utm_source="x" * 121)
        )
        assert resp.status_code == 422

    def test_oversized_email_rejected(self, client):
        _override_db(FakeWaitlistSession())
        resp = client.post(
            "/api/v1/early-access", json=_payload(email="a" * 250 + "@x.com")
        )
        assert resp.status_code == 422


# ===========================================================================
# Duplicate signup behavior + first-touch attribution
# ===========================================================================


class TestDuplicateSignup:
    def test_duplicate_returns_friendly_success(self, client):
        lead = _existing_lead()
        db = FakeWaitlistSession(leads=[lead])
        _override_db(db)

        resp = client.post("/api/v1/early-access", json=_payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["already_registered"] is True
        # No new row was inserted.
        assert db.added == []

    def test_duplicate_preserves_first_touch_attribution(self, client):
        original_created = datetime.now(timezone.utc) - timedelta(days=7)
        lead = _existing_lead(created_at=original_created)
        db = FakeWaitlistSession(leads=[lead])
        _override_db(db)

        resp = client.post(
            "/api/v1/early-access",
            json=_payload(
                referral_source="paid",
                utm_source="google",
                utm_campaign="later-campaign",
            ),
        )
        assert resp.status_code == 200
        # First-touch attribution untouched.
        assert lead.referral_source == "themissrubie"
        assert lead.utm_source == "newsletter"
        assert lead.utm_campaign == "launch"
        assert lead.created_at == original_created

    def test_duplicate_fills_only_empty_attribution(self, client):
        lead = _existing_lead(referral_source=None, utm_medium=None)
        db = FakeWaitlistSession(leads=[lead])
        _override_db(db)

        resp = client.post(
            "/api/v1/early-access",
            json=_payload(referral_source="campus", utm_medium="email", utm_source="ignored"),
        )
        assert resp.status_code == 200
        assert lead.referral_source == "campus"   # empty -> filled
        assert lead.utm_medium == "email"          # empty -> filled
        assert lead.utm_source == "newsletter"     # set -> preserved

    def test_duplicate_refreshes_profile_and_consent(self, client):
        old_consent = datetime.now(timezone.utc) - timedelta(days=7)
        lead = _existing_lead(consent_timestamp=old_consent, education_type=None)
        db = FakeWaitlistSession(leads=[lead])
        _override_db(db)

        resp = client.post(
            "/api/v1/early-access",
            json=_payload(
                first_name="Jamie R.",
                audience_type="parent",
                education_type="graduate",
                consent_source="early_access_form_v2",
            ),
        )
        assert resp.status_code == 200
        assert lead.first_name == "Jamie R."
        assert lead.audience_type == "parent"
        assert lead.education_type == "graduate"
        assert lead.consent_timestamp > old_consent
        assert lead.consent_source == "early_access_form_v2"


# ===========================================================================
# EmailOctopus provider sync (after durable save)
# ===========================================================================


class TestProviderSync:
    def test_provider_success_marks_synced(self, client):
        db = FakeWaitlistSession()
        _override_db(db)
        provider = MagicMock()
        provider.subscribe_or_update.return_value = ProviderSyncResult(status="synced")

        with patch("app.main.get_email_marketing_provider", return_value=provider):
            resp = client.post("/api/v1/early-access", json=_payload())

        assert resp.status_code == 201
        lead = db.added[0]
        assert lead.provider_sync_status == "synced"
        assert lead.provider_synced_at is not None
        provider.subscribe_or_update.assert_called_once()
        kwargs = provider.subscribe_or_update.call_args.kwargs
        assert kwargs["email"] == "jamie@example.com"
        assert kwargs["first_name"] == "Jamie"
        assert kwargs["tags"] == ["WAITLIST", "STUDENT"]

    def test_provider_failure_still_returns_success(self, client):
        db = FakeWaitlistSession()
        _override_db(db)
        provider = MagicMock()
        provider.subscribe_or_update.return_value = ProviderSyncResult(
            status="failed", error="HTTP 500: upstream exploded"
        )

        with patch("app.main.get_email_marketing_provider", return_value=provider):
            resp = client.post("/api/v1/early-access", json=_payload())

        # The signup succeeded — the lead is durable in the EdFintia DB.
        assert resp.status_code == 201
        assert resp.json()["status"] == "ok"
        lead = db.added[0]
        assert lead.provider_sync_status == "failed"
        assert lead.provider_last_error == "HTTP 500: upstream exploded"

    def test_provider_exception_still_returns_success(self, client):
        db = FakeWaitlistSession()
        _override_db(db)
        provider = MagicMock()
        provider.subscribe_or_update.side_effect = RuntimeError("network down")

        with patch("app.main.get_email_marketing_provider", return_value=provider):
            resp = client.post("/api/v1/early-access", json=_payload())

        assert resp.status_code == 201
        # Lead stays pending for a later retry sweep.
        assert db.added[0].provider_sync_status == "pending"

    def test_provider_unconfigured_marks_skipped(self, client):
        db = FakeWaitlistSession()
        _override_db(db)
        resp = client.post("/api/v1/early-access", json=_payload())
        assert resp.status_code == 201
        assert db.added[0].provider_sync_status == "skipped"

    def test_response_never_leaks_provider_details(self, client):
        db = FakeWaitlistSession()
        _override_db(db)
        provider = MagicMock()
        provider.subscribe_or_update.return_value = ProviderSyncResult(
            status="failed", error="HTTP 401: bad api key secret-key-123"
        )
        with patch("app.main.get_email_marketing_provider", return_value=provider):
            resp = client.post("/api/v1/early-access", json=_payload())
        assert resp.status_code == 201
        assert "secret-key-123" not in resp.text
        assert "HTTP 401" not in resp.text


# ===========================================================================
# EmailOctopus adapter (unit level)
# ===========================================================================


class TestEmailOctopusAdapter:
    def test_upsert_uses_md5_digest_url_and_body_key(self):
        provider = EmailOctopusProvider(api_key="k-secret", list_id="list-9")
        fake_resp = MagicMock(status_code=200)
        fake_resp.json.return_value = {}

        with patch("app.services.email_marketing.requests.put", return_value=fake_resp) as put:
            result = provider.subscribe_or_update(
                email="Jamie@Example.com",
                first_name="Jamie",
                tags=["WAITLIST", "STUDENT"],
                fields={"AudienceType": "student"},
            )

        assert result.status == "synced"
        url = put.call_args.args[0]
        digest = hashlib.md5(b"jamie@example.com").hexdigest()
        assert url.endswith(f"/lists/list-9/contacts/{digest}")
        body = put.call_args.kwargs["json"]
        assert body["api_key"] == "k-secret"          # server-side only
        assert body["email_address"] == "jamie@example.com"
        assert body["fields"]["FirstName"] == "Jamie"
        assert body["tags"] == {"WAITLIST": True, "STUDENT": True}

    def test_non_2xx_returns_failed(self):
        provider = EmailOctopusProvider(api_key="k", list_id="l")
        fake_resp = MagicMock(status_code=500)
        fake_resp.json.return_value = {"error": {"message": "boom"}}
        with patch("app.services.email_marketing.requests.put", return_value=fake_resp):
            result = provider.subscribe_or_update(
                email="a@b.com", first_name="A", tags=[]
            )
        assert result.status == "failed"
        assert "500" in result.error

    def test_request_exception_returns_failed(self):
        provider = EmailOctopusProvider(api_key="k", list_id="l")
        with patch(
            "app.services.email_marketing.requests.put",
            side_effect=ConnectionError("dns failure"),
        ):
            result = provider.subscribe_or_update(
                email="a@b.com", first_name="A", tags=[]
            )
        assert result.status == "failed"
        assert "dns failure" in result.error

    def test_tag_mapping(self):
        assert waitlist_tags_for_audience("student") == ["WAITLIST", "STUDENT"]
        assert waitlist_tags_for_audience("parent") == ["WAITLIST", "PARENT"]
        assert waitlist_tags_for_audience("college_staff") == ["WAITLIST", "COLLEGE"]
        assert waitlist_tags_for_audience("counselor") == ["WAITLIST", "COUNSELOR"]
        assert waitlist_tags_for_audience("other") == ["WAITLIST", "OTHER"]
        assert waitlist_tags_for_audience(None) == ["WAITLIST"]


# ===========================================================================
# Rate limiting
# ===========================================================================


class TestRateLimiting:
    def test_rate_limit_returns_429(self, client):
        _override_db(FakeWaitlistSession())
        with patch.object(early_access_rate_limiter, "limit", 2):
            assert client.post("/api/v1/early-access", json=_payload()).status_code == 201
            assert client.post("/api/v1/early-access", json=_payload()).status_code == 200
            resp = client.post("/api/v1/early-access", json=_payload())
            assert resp.status_code == 429


# ===========================================================================
# Lead -> account conversion
# ===========================================================================


class TestConversion:
    def test_signup_marks_converted_when_account_exists(self, client):
        account = Profile()
        account.id = uuid4()
        account.email = "jamie@example.com"
        db = FakeWaitlistSession(profiles=[account])
        _override_db(db)

        resp = client.post("/api/v1/early-access", json=_payload())
        assert resp.status_code == 201
        lead = db.added[0]
        assert lead.converted_to_user is True
        assert lead.converted_at is not None
        assert lead.converted_user_id == account.id

    def test_profile_creation_marks_lead_converted(
        self, client, authenticated_client_factory
    ):
        lead = _existing_lead()
        db = FakeWaitlistSession(leads=[lead])
        _override_db(db)

        authed = authenticated_client_factory(app)
        resp = authed.post(
            "/profiles",
            json={"full_name": "Jamie", "email": "jamie@example.com"},
        )
        assert resp.status_code == 200
        assert lead.converted_to_user is True
        assert lead.converted_at is not None
        assert lead.converted_user_id == DEMO_USER_ID

    def test_profile_creation_leaves_unrelated_leads(
        self, client, authenticated_client_factory
    ):
        lead = _existing_lead(email="someoneelse@example.com")
        db = FakeWaitlistSession(leads=[lead])
        _override_db(db)

        authed = authenticated_client_factory(app)
        resp = authed.post(
            "/profiles",
            json={"full_name": "Jamie", "email": "jamie@example.com"},
        )
        assert resp.status_code == 200
        assert lead.converted_to_user is False


# ===========================================================================
# Model / schema shape
# ===========================================================================


class TestWaitlistModel:
    def test_model_columns_exist(self):
        cols = WaitlistLead.__table__.columns
        for name in [
            "email", "first_name", "audience_type", "education_type", "status",
            "referral_source", "referral_code", "referred_by",
            "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
            "landing_page", "consent_timestamp", "consent_source",
            "provider_sync_status", "provider_synced_at", "provider_last_error",
            "converted_to_user", "converted_at", "created_at", "updated_at",
        ]:
            assert name in cols, f"missing column {name}"

    def test_email_unique(self):
        assert WaitlistLead.__table__.c.email.unique is True
