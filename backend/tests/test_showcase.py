"""Public Discovery Showcase endpoint tests.

GET /api/scholarships/showcase is a public, read-only, profile-free sample
of consumer-discoverable catalog records. These tests prove:

- the route is registered in the public auth allowlist and requires no
  token / no profile / no search quota
- eligibility is enforced in SQL via lifecycle.discoverable_filters —
  the same predicates is_discoverable() evaluates — so draft, stale,
  archived, and needs_review records can never reach the payload
- the response is a whitelisted slim contract (no identity keys, source
  internals, match scores, or per-user state)
- selection is capped at 10, ordered by a deterministic md5(record id ||
  UTC-day) seed, cached per day, and rate-limited for load protection
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.main as main_mod
from app.database import get_db
from app.main import app, _showcase_cache, showcase_rate_limiter
from app.middleware.auth import PUBLIC_PATHS
from app.models.models import Scholarship
from app.services import lifecycle

SHOWCASE_PATH = "/api/scholarships/showcase"

EXPECTED_KEYS = {
    "scholarship_id",
    "title",
    "provider",
    "award_amount",
    "deadline",
    "eligible_disciplines",
    "matching_tags",
    "metro_restrictions",
    "funding_type",
    "has_service_commitment",
    "employment_required",
    "verification_status",
}

# Fields that must never appear in ANY public payload. portal_url is the
# gated value: it is revealed only via the authenticated application-link
# endpoint, never in showcase or public detail responses.
FORBIDDEN_KEYS = {
    "id",
    "portal_url",
    "application_url",
    "url",
    "identity_key",
    "identity_fallback_key",
    "source_url",
    "extraction_method",
    "verified_fields",
    "verified_at",
    "last_seen_at",
    "last_checked_at",
    "consecutive_misses",
    "is_archived",
    "archive_reason",
    "lifecycle_status",
    "score",
    "missing_criteria",
    "is_dismissed",
    "tracking_id",
    "user_id",
    "tracks",
}


def _scholarship(**kw) -> SimpleNamespace:
    """Attribute bag standing in for a Scholarship ORM row.

    SimpleNamespace (not MagicMock) — pydantic from_attributes validation
    must see exactly the declared attribute set; a MagicMock's auto-created
    attributes (e.g. ``tracks``) would distort the whitelist assertions.
    """
    defaults = {
        "id": uuid4(),
        "title": "Sample Opportunity",
        "provider": "Test Provider",
        "portal_url": "https://example.org/apply",
        "award_amount": 2500,
        "deadline": date(2030, 5, 1),
        "eligible_disciplines": ["nursing"],
        "matching_tags": ["undergraduate"],
        "metro_restrictions": [],
        "funding_type": "scholarship",
        "has_service_commitment": False,
        "employment_required": False,
        "verification_status": "verified",
        # Internal fields that must not leak through serialization.
        "identity_key": "internal-key",
        "identity_fallback_key": "fallback-key",
        "source_url": "https://internal.source/page",
        "extraction_method": "crawler",
        "lifecycle_status": lifecycle.PUBLISHED,
        "archive_reason": None,
        "is_archived": False,
        # Detail-surface fields
        "estimated_next_cycle": None,
        "eligible_credentials": ["BSN"],
        "academic_levels": ["undergraduate"],
        "is_general_major": False,
        "min_gpa": 3.0,
        "max_sai": 12000,
        "scope": "state",
        "state_restrictions": ["TX"],
        "county_restrictions": [],
        "city_restrictions": [],
        "min_employment_tenure_months": None,
        "annual_benefit_cap": None,
        "benefit_coverage_model": None,
        "partner_network": None,
        "service_commitment_duration_months": None,
        "vendor_platform": None,
        "provider_type": "nonprofit",
        "provider_mission": "Supporting rural nurses.",
        "provider_core_values": ["service"],
        "target_community": None,
        "is_local": False,
        "competition_level": "medium",
        "required_affiliations": [],
        "citizenship_requirement": None,
        "enrollment_statuses": ["full_time"],
        "institution_restrictions": [],
        "military_affiliation_requirement": None,
        "public_description": "A grant supporting rural nursing students.",
        "tracks": [{"title": "T", "detail_url": "https://x.example/leak"}],
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _db_returning(rows):
    """Mock DB whose Scholarship query chain returns `rows` and records the
    filter/order/limit calls for clause inspection."""
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.order_by.return_value = q
    q.limit.return_value = q
    q.all.return_value = rows
    db.query.return_value = q
    return db, q


@pytest.fixture(autouse=True)
def clean_showcase_state():
    _showcase_cache.clear()
    showcase_rate_limiter.reset()
    yield
    _showcase_cache.clear()
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    # Bare client — NO Authorization header. The showcase is public.
    return TestClient(app)


def _override_db(db):
    app.dependency_overrides[get_db] = lambda: db


def _compiled(criterion) -> str:
    return str(
        criterion.compile(compile_kwargs={"literal_binds": True})
    )


class TestPublicAccess:
    def test_route_in_public_allowlist(self):
        assert SHOWCASE_PATH in PUBLIC_PATHS

    def test_anonymous_request_200_no_token_no_profile(self, client):
        db, _ = _db_returning([_scholarship()])
        _override_db(db)

        resp = client.get(SHOWCASE_PATH)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_no_profile_or_tracking_tables_queried(self, client):
        """Showcase must not touch profiles, usage/quota, or tracking rows."""
        db, _ = _db_returning([_scholarship()])
        _override_db(db)

        resp = client.get(SHOWCASE_PATH)
        assert resp.status_code == 200
        queried = [call.args[0] for call in db.query.call_args_list]
        assert queried == [Scholarship]  # the only table touched

    def test_empty_catalog_returns_200_empty_list(self, client):
        db, _ = _db_returning([])
        _override_db(db)

        resp = client.get(SHOWCASE_PATH)
        assert resp.status_code == 200
        assert resp.json() == []


class TestEligibility:
    def test_sql_enforces_discoverable_predicates(self, client):
        """The query must carry BOTH is_discoverable() conditions in SQL —
        records are excluded at the query layer, not filtered in Python."""
        db, q = _db_returning([])
        _override_db(db)

        client.get(SHOWCASE_PATH)

        assert q.filter.call_count == 1
        clauses = q.filter.call_args.args
        compiled = sorted(_compiled(c) for c in clauses)
        assert len(clauses) == 2
        assert any(
            "lifecycle_status" in c and f"'{lifecycle.PUBLISHED}'" in c
            for c in compiled
        )
        assert any(
            "verification_status" in c and "needs_review" in c and "!=" in c
            for c in compiled
        )

    def test_shared_helper_matches_object_predicate(self):
        """discoverable_filters() must mirror is_discoverable() exactly."""
        clauses = lifecycle.discoverable_filters(Scholarship)
        compiled = [_compiled(c) for c in clauses]
        assert any("lifecycle_status" in c and lifecycle.PUBLISHED in c for c in compiled)
        assert any("verification_status" in c and "needs_review" in c for c in compiled)

    @pytest.mark.parametrize(
        "status,verif,expected",
        [
            (lifecycle.PUBLISHED, "verified", True),
            (lifecycle.PUBLISHED, "legacy_unverified", True),
            (lifecycle.DRAFT, "verified", False),
            (lifecycle.STALE, "verified", False),
            (lifecycle.ARCHIVED, "verified", False),
            (lifecycle.PUBLISHED, "needs_review", False),
        ],
    )
    def test_excluded_states_never_discoverable(self, status, verif, expected):
        s = _scholarship(lifecycle_status=status, verification_status=verif)
        s.is_archived = status == lifecycle.ARCHIVED
        assert lifecycle.is_discoverable(s) is expected


class TestContract:
    def test_response_whitelist(self, client):
        s = _scholarship()
        _override_db(_db_returning([s])[0])

        resp = client.get(SHOWCASE_PATH)
        assert resp.status_code == 200
        item = resp.json()[0]
        assert set(item.keys()) == EXPECTED_KEYS
        assert FORBIDDEN_KEYS.isdisjoint(item.keys())
        assert item["scholarship_id"] == str(s.id)

    def test_unknown_award_and_deadline_serialize_null(self, client):
        s = _scholarship(award_amount=None, deadline=None)
        _override_db(_db_returning([s])[0])

        item = client.get(SHOWCASE_PATH).json()[0]
        assert item["award_amount"] is None
        assert item["deadline"] is None


class TestSelectionRotationCache:
    def test_limit_10_applied(self, client):
        db, q = _db_returning([])
        _override_db(db)
        client.get(SHOWCASE_PATH)
        assert q.limit.call_args.args[0] == main_mod.SHOWCASE_LIMIT == 10

    def test_same_day_ordering_deterministic(self, client):
        """Two same-seed calls produce identical md5 ordering clauses."""
        compiled_clauses = []
        for _ in range(2):
            _showcase_cache.clear()
            db, q = _db_returning([])
            _override_db(db)
            with patch.object(
                main_mod, "_showcase_day_seed", return_value="2026-01-05"
            ):
                client.get(SHOWCASE_PATH)
            clause = q.order_by.call_args.args[0]
            compiled_clauses.append(_compiled(clause))
        assert compiled_clauses[0] == compiled_clauses[1]
        assert "'2026-01-05'" in compiled_clauses[0]
        assert "md5" in compiled_clauses[0].lower()

    def test_different_day_rotates_seed(self, client):
        compiled_clauses = []
        for day in ("2026-01-05", "2026-01-06"):
            _showcase_cache.clear()
            db, q = _db_returning([])
            _override_db(db)
            with patch.object(main_mod, "_showcase_day_seed", return_value=day):
                client.get(SHOWCASE_PATH)
            compiled_clauses.append(_compiled(q.order_by.call_args.args[0]))
        assert compiled_clauses[0] != compiled_clauses[1]
        assert "'2026-01-06'" in compiled_clauses[1]

    def test_cache_control_header(self, client):
        db, _ = _db_returning([])
        _override_db(db)
        resp = client.get(SHOWCASE_PATH)
        assert resp.headers["Cache-Control"] == "public, max-age=300"

    def test_in_process_day_cache(self, client):
        """Second same-day request is served from cache — DB hit once."""
        db, _ = _db_returning([_scholarship()])
        _override_db(db)
        with patch.object(
            main_mod, "_showcase_day_seed", return_value="2026-02-02"
        ):
            r1 = client.get(SHOWCASE_PATH)
            r2 = client.get(SHOWCASE_PATH)
        assert r1.json() == r2.json()
        assert db.query.call_count == 1

    def test_rate_limit_returns_429(self, client):
        with patch.object(
            showcase_rate_limiter, "allow", return_value=False
        ):
            resp = client.get(SHOWCASE_PATH)
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Public opportunity detail — GET /api/scholarships/showcase/{id}
# ---------------------------------------------------------------------------

DETAIL_PATH_TEMPLATE = SHOWCASE_PATH + "/{sid}"


def _detail_db(scholarship):
    """Mock DB for the single-record detail query chain (filter…first())."""
    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.first.return_value = scholarship
    db.query.return_value = q
    return db, q


class TestPublicDetail:
    def _get(self, client, scholarship):
        sid = scholarship.id if scholarship else uuid4()
        db, q = _detail_db(scholarship)
        _override_db(db)
        return client.get(DETAIL_PATH_TEMPLATE.format(sid=sid)), q, db

    def test_anonymous_200_whitelisted_fields(self, client):
        s = _scholarship()
        resp, _, _ = self._get(client, s)
        assert resp.status_code == 200
        item = resp.json()
        assert item["scholarship_id"] == str(s.id)
        assert item["title"] == "Sample Opportunity"
        assert item["provider_mission"] == "Supporting rural nurses."
        # Real structured eligibility data present.
        assert item["state_restrictions"] == ["TX"]
        assert item["eligible_credentials"] == ["BSN"]
        assert item["min_gpa"] == 3.0

    def test_no_application_url_or_internals_anywhere(self, client):
        resp, _, _ = self._get(client, _scholarship())
        item = resp.json()
        assert FORBIDDEN_KEYS.isdisjoint(item.keys())
        # Belt-and-suspenders: scan the raw body for URL-looking strings
        # that could smuggle a provider link.
        body = resp.text
        for url in ("example.org/apply", "x.example/leak", "internal.source"):
            assert url not in body

    def test_unknown_fields_serialize_cleanly(self, client):
        s = _scholarship(
            award_amount=None, deadline=None, provider_mission=None,
            funding_type=None, scope=None, min_gpa=0.0,
        )
        resp, _, _ = self._get(client, s)
        assert resp.status_code == 200
        item = resp.json()
        assert item["award_amount"] is None
        assert item["deadline"] is None
        assert item["funding_type"] is None

    def test_missing_record_404(self, client):
        resp, _, _ = self._get(client, None)
        assert resp.status_code == 404

    def test_discoverable_filter_applied_to_id_lookup(self, client):
        """The id query must ALSO carry both discoverable clauses."""
        resp, q, _ = self._get(client, _scholarship())
        assert resp.status_code == 200
        clauses = [
            c
            for call in q.filter.call_args_list
            for c in call.args
        ]
        compiled = [_compiled(c) for c in clauses]
        assert any("lifecycle_status" in c and lifecycle.PUBLISHED in c for c in compiled)
        assert any("verification_status" in c and "needs_review" in c for c in compiled)

    def test_stored_public_description_is_returned(self, client):
        """The persisted narrative reaches the public contract — real
        catalog data, not generated on request."""
        s = _scholarship(
            public_description=(
                "The Rural Health Scholarship funds nursing students who "
                "commit to two years of clinical service in underserved "
                "communities."
            )
        )
        resp, _, _ = self._get(client, s)
        assert resp.status_code == 200
        assert resp.json()["public_description"] == s.public_description

    def test_null_public_description_serializes_null(self, client):
        """NULL descriptions are a valid state — the field serializes as
        null, never as fabricated placeholder text."""
        resp, _, _ = self._get(client, _scholarship(public_description=None))
        assert resp.status_code == 200
        assert resp.json()["public_description"] is None

    def test_detail_get_never_invokes_llm(self, client):
        """Descriptions are persisted data: a public detail GET must never
        call the extraction LLM at request time."""
        from scrapers import llm_parser

        with patch.object(
            llm_parser,
            "extract_opportunities_with_llm",
            side_effect=AssertionError("runtime LLM call on public detail"),
        ) as llm:
            resp, _, _ = self._get(client, _scholarship())
        assert resp.status_code == 200
        llm.assert_not_called()

    def test_only_scholarship_table_queried(self, client):
        resp, _, db = self._get(client, _scholarship())
        assert resp.status_code == 200
        assert [c.args[0] for c in db.query.call_args_list] == [Scholarship]

    def test_cache_control_public(self, client):
        resp, _, _ = self._get(client, _scholarship())
        assert resp.headers["Cache-Control"] == "public, max-age=300"

    def test_rate_limited_429(self, client):
        with patch.object(showcase_rate_limiter, "allow", return_value=False):
            resp = client.get(DETAIL_PATH_TEMPLATE.format(sid=uuid4()))
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Authenticated application link — GET /api/v1/scholarships/{id}/application-link
# ---------------------------------------------------------------------------

APP_LINK_TEMPLATE = "/api/v1/scholarships/{sid}/application-link"


class TestApplicationLink:
    def test_anonymous_401_no_token(self, client):
        """Anonymous requests are rejected by the middleware before the
        endpoint runs — the URL never reaches an unauthenticated client.
        Production middleware path forced so a dev-mode ambient env can't
        turn an unauthenticated request into a demo-user request."""
        import os

        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            resp = client.get(APP_LINK_TEMPLATE.format(sid=uuid4()))
        assert resp.status_code == 401

    def test_application_link_not_publicly_allowlisted(self):
        """The route must never appear in the public allowlists — its
        protection is middleware-level, and allowing it would leak the URL
        to anonymous callers without any code noticing."""
        from app.middleware.auth import PUBLIC_PREFIXES

        assert not any(
            APP_LINK_TEMPLATE.format(sid="x").startswith(p)
            for p in PUBLIC_PREFIXES
        )
        assert APP_LINK_TEMPLATE.format(sid="x") not in PUBLIC_PATHS

    def test_authenticated_gets_official_url(self, authenticated_client_factory):
        s = _scholarship()
        db, _ = _detail_db(s)
        _override_db(db)
        authed = authenticated_client_factory(app)
        resp = authed.get(APP_LINK_TEMPLATE.format(sid=s.id))
        assert resp.status_code == 200
        assert resp.json() == {"url": "https://example.org/apply"}

    def test_free_and_premium_treated_identically(self, authenticated_client_factory):
        """No tier gate: the endpoint never queries profiles/subscriptions,
        so free and premium users get the same response."""
        s = _scholarship()
        db, _ = _detail_db(s)
        _override_db(db)
        authed = authenticated_client_factory(app)
        resp = authed.get(APP_LINK_TEMPLATE.format(sid=s.id))
        assert resp.status_code == 200
        queried = [c.args[0] for c in db.query.call_args_list]
        assert queried == [Scholarship]  # no Profile/subscription lookup

    def test_non_discoverable_404(self, authenticated_client_factory):
        db, _ = _detail_db(None)
        _override_db(db)
        authed = authenticated_client_factory(app)
        resp = authed.get(APP_LINK_TEMPLATE.format(sid=uuid4()))
        assert resp.status_code == 404
