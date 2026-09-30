"""C4 persisted opportunity identity regression tests.

Covers:
  - canonical URL identity (tracking params/fragments/www/slashes/scheme)
  - identity-bearing query parameters (pgm_id etc.) vs. unverifiable params
  - listing/weak URL handling (portal == source, bare homepage, listing paths)
  - title+provider fallback identity and generic-title exclusion
  - indexed upsert lookup (no full-table scan), unique-race recovery
  - annual-cycle identity stability and lifecycle preservation on refresh
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.models import Scholarship
from app.services import lifecycle
from tests.conftest import FakeCatalogSession
from scrapers.runner import upsert_scholarship
from scrapers.schema import ScholarshipExtract
from scrapers.utils.identity import (
    canonical_identity_url,
    compute_identity_keys,
    is_weak_identity_url,
    title_provider_key,
)

FUTURE = date.today() + timedelta(days=90)
PAST = date.today() - timedelta(days=30)


def _extract(**kw) -> ScholarshipExtract:
    defaults = dict(
        title="Merit Award",
        provider="Example Foundation",
        portal_url="https://www.example.org/scholarships/merit",
    )
    defaults.update(kw)
    return ScholarshipExtract(**defaults)


def _row(**kw) -> Scholarship:
    defaults = dict(
        id=uuid.uuid4(), title="Merit Award", provider="Example Foundation",
        portal_url="https://www.example.org/scholarships/merit",
        deadline=FUTURE, lifecycle_status="published", archive_reason=None,
        is_archived=False, consecutive_misses=0, created_at=datetime.utcnow(),
    )
    defaults.update(kw)
    s = Scholarship(**defaults)
    k, f = compute_identity_keys(s.title, s.provider, s.portal_url, s.source_url)
    s.identity_key, s.identity_fallback_key = k, f
    return s


# ---------------------------------------------------------------------------
# Canonical URL identity
# ---------------------------------------------------------------------------

class TestCanonicalUrl:
    def test_utm_fragment_www_trailing_slash_deduplicate(self):
        a = canonical_identity_url("https://www.example.org/scholarships/merit/?utm_source=email#apply")
        b = canonical_identity_url("http://example.org/scholarships/merit")
        assert a == b == "https://example.org/scholarships/merit"

    def test_scheme_difference_deduplicates(self):
        assert canonical_identity_url("http://example.org/a") == canonical_identity_url("https://example.org/a")

    def test_identity_bearing_param_is_preserved(self):
        c = canonical_identity_url("https://health.ri.gov/programs/detail.php?pgm_id=141&utm_source=x")
        assert c == "https://health.ri.gov/programs/detail.php?pgm_id=141"

    def test_distinct_program_ids_stay_distinct(self):
        a = canonical_identity_url("https://health.ri.gov/programs/detail.php?pgm_id=141")
        b = canonical_identity_url("https://health.ri.gov/programs/detail.php?pgm_id=142")
        assert a != b

    def test_identity_param_among_junk_params(self):
        a = canonical_identity_url("https://x.org/detail.php?utm_source=e&pgm_id=7&ref=nav")
        b = canonical_identity_url("https://x.org/detail.php?pgm_id=7&fbclid=abc")
        assert a == b == "https://x.org/detail.php?pgm_id=7"

    def test_param_order_does_not_change_identity(self):
        a = canonical_identity_url("https://x.org/d.php?pgm_id=1&id=2")
        b = canonical_identity_url("https://x.org/d.php?id=2&pgm_id=1")
        assert a == b

    def test_non_allowlisted_params_produce_same_canonical_but_weak_url(self):
        # ?prog=1 vs ?prog=2 canonicalize to the same URL — but the URL is
        # then treated as WEAK so distinct programs can't merge on it.
        a = canonical_identity_url("https://x.org/detail.php?prog=1")
        b = canonical_identity_url("https://x.org/detail.php?prog=2")
        assert a == b == "https://x.org/detail.php"
        k1, _ = compute_identity_keys("A Award", "P", "https://x.org/detail.php?prog=1")
        k2, _ = compute_identity_keys("B Award", "P", "https://x.org/detail.php?prog=2")
        assert k1 != k2  # tp identities distinguish


# ---------------------------------------------------------------------------
# Weak / listing URLs
# ---------------------------------------------------------------------------

class TestWeakUrls:
    def test_bare_homepage_is_weak(self):
        assert is_weak_identity_url("https://example.org/") is True

    def test_listing_path_is_weak(self):
        for path in ("/scholarships", "/financial-aid", "/grants", "/scholarships.php"):
            assert is_weak_identity_url(f"https://example.org{path}") is True

    def test_specific_path_is_strong(self):
        assert is_weak_identity_url("https://example.org/scholarships/nursing-award") is False

    def test_identity_params_make_url_strong(self):
        assert is_weak_identity_url("https://health.ri.gov/programs/detail.php?pgm_id=141") is False

    def test_portal_equal_to_source_is_weak(self):
        canon = "https://f.org/programs/specific-award"
        assert is_weak_identity_url(canon, canon) is True
        assert is_weak_identity_url(canon, "https://f.org/other") is False


# ---------------------------------------------------------------------------
# Identity precedence + title/provider fallback
# ---------------------------------------------------------------------------

class TestIdentityPrecedence:
    def test_strong_url_produces_url_key_with_tp_fallback(self):
        key, fb = compute_identity_keys("Merit Award", "Fdn", "https://f.org/scholarships/merit")
        assert key == "u:https://f.org/scholarships/merit"
        assert fb == "tp:merit award|fdn"

    def test_weak_url_falls_to_title_provider(self):
        key, fb = compute_identity_keys(
            "Merit Award", "Fdn", "https://f.org/scholarships",
            source_url="https://f.org/other-page",
        )
        assert key == "tp:merit award|fdn"
        assert fb is None

    def test_listing_children_with_same_source_get_distinct_tp_keys(self):
        """C5 pre-shape: same listing/source URL, same provider, different titles."""
        src = "https://f.org/scholarships"
        k1, _ = compute_identity_keys("Nursing Award", "Fdn", src, source_url=src)
        k2, _ = compute_identity_keys("Teaching Award", "Fdn", src, source_url=src)
        assert k1 != k2
        assert k1.startswith("tp:") and k2.startswith("tp:")

    def test_generic_title_cannot_become_tp_identity(self):
        assert title_provider_key("Scholarships", "Fdn") is None
        key, _ = compute_identity_keys("Scholarships", "Fdn", "https://f.org/scholarships/x")
        assert key == "u:https://f.org/scholarships/x"

    def test_no_stable_identity_raises_in_upsert(self):
        db = FakeCatalogSession()
        with pytest.raises(ValueError):
            upsert_scholarship(db, _extract(title="Merit Award", provider="", portal_url=""))


# ---------------------------------------------------------------------------
# Upsert: indexed lookup, no full-table scan
# ---------------------------------------------------------------------------

class TestUpsertIdentity:
    def test_create_writes_persisted_identity(self):
        db = FakeCatalogSession()
        s, action = upsert_scholarship(db, _extract())
        assert action == "created"
        assert s.identity_key == "u:https://example.org/scholarships/merit"
        assert s.identity_fallback_key == "tp:merit award|example foundation"

    def test_canonical_variants_update_same_row(self):
        db = FakeCatalogSession()
        s1, _ = upsert_scholarship(db, _extract())
        s2, action = upsert_scholarship(db, _extract(
            portal_url="http://www.example.org/scholarships/merit/?utm_source=x#top",
            award_amount=9000,
        ))
        assert action == "updated"
        assert s2 is s1 and s1.award_amount == 9000
        assert len(db.rows) == 1

    def test_provider_url_migration_matches_via_tp_fallback(self):
        existing = _row(portal_url="https://old.example.org/apply/merit")
        db = FakeCatalogSession([existing])
        extract = _extract(portal_url="https://new.example.org/apply/merit")
        s, action = upsert_scholarship(db, extract)
        assert action == "updated" and s is existing
        # Identity absorbed the new canonical URL.
        assert existing.identity_key == "u:https://new.example.org/apply/merit"
        assert len(db.rows) == 1

    def test_different_pgm_ids_create_distinct_rows(self):
        db = FakeCatalogSession()
        upsert_scholarship(db, _extract(
            title="Osteopathic Scholarship", provider="RI Health",
            portal_url="https://health.ri.gov/programs/detail.php?pgm_id=141",
        ))
        upsert_scholarship(db, _extract(
            title="Dental Scholarship", provider="RI Health",
            portal_url="https://health.ri.gov/programs/detail.php?pgm_id=142",
        ))
        assert len(db.rows) == 2

    def test_shared_listing_url_different_titles_stay_distinct(self):
        src = "https://f.org/scholarships"
        db = FakeCatalogSession()
        upsert_scholarship(db, _extract(
            title="Nursing Award", provider="Fdn", portal_url=src, source_url=src))
        upsert_scholarship(db, _extract(
            title="Teaching Award", provider="Fdn", portal_url=src, source_url=src))
        assert len(db.rows) == 2

    def test_shared_listing_url_same_title_merges(self):
        src = "https://f.org/scholarships"
        db = FakeCatalogSession()
        upsert_scholarship(db, _extract(
            title="Nursing Award", provider="Fdn", portal_url=src, source_url=src))
        _, action = upsert_scholarship(db, _extract(
            title="Nursing Award", provider="Fdn", portal_url=src, source_url=src,
            award_amount=1000))
        assert action == "updated" and len(db.rows) == 1

    def test_legacy_null_key_row_matches_via_compat_scan(self):
        existing = _row()
        existing.identity_key = None  # predates the 024 backfill
        existing.identity_fallback_key = None
        db = FakeCatalogSession([existing])
        s, action = upsert_scholarship(db, _extract())
        assert action == "updated" and s is existing
        assert existing.identity_key == "u:https://example.org/scholarships/merit"

    def test_annual_cycle_is_one_row(self):
        db = FakeCatalogSession()
        s1, _ = upsert_scholarship(db, _extract(deadline=PAST.isoformat()))
        assert lifecycle.current_status(s1) == "archived"
        assert s1.archive_reason == "deadline_passed"
        s2, action = upsert_scholarship(db, _extract(deadline=FUTURE.isoformat()))
        assert action == "updated" and s2 is s1 and len(db.rows) == 1
        assert lifecycle.current_status(s1) == "published"
        assert s1.deadline == FUTURE

    def test_dead_link_not_resurrected_by_plain_refresh(self):
        existing = _row(lifecycle_status="archived", archive_reason="dead_link",
                        is_archived=True, deadline=None)
        db = FakeCatalogSession([existing])
        upsert_scholarship(db, _extract(deadline=None), destination_verified=False)
        assert existing.lifecycle_status == "archived"
        assert existing.last_seen_at is not None  # still an observation

    def test_no_unfiltered_table_scan(self):
        """FakeCatalogSession._FakeQuery.all raises if .filter() was never
        called — reaching here proves every lookup was filtered/indexed."""
        existing = _row()
        db = FakeCatalogSession([existing])
        upsert_scholarship(db, _extract())
        upsert_scholarship(db, _extract(award_amount=1))


# ---------------------------------------------------------------------------
# Unique-race recovery
# ---------------------------------------------------------------------------

class TestConcurrencyRecovery:
    def test_insert_race_recovers_to_update(self):
        """Loser's commit raises IntegrityError; rollback reveals the winner's
        row; upsert recovers by updating it — one identity, one row."""
        winner = _row(award_amount=1111)
        db = FakeCatalogSession()
        db.commit_errors = [IntegrityError("INSERT", {}, Exception("duplicate key"))]
        db.on_rollback = lambda: db.rows.append(winner)

        s, action = upsert_scholarship(db, _extract(award_amount=2222))
        assert action == "updated" and s is winner
        assert winner.award_amount == 2222
        # The loser's pending insert was discarded by rollback.
        assert db.rows == [winner]

    def test_insert_race_with_no_winner_reraises(self):
        db = FakeCatalogSession()
        db.commit_errors = [IntegrityError("INSERT", {}, Exception("other constraint"))]
        with pytest.raises(IntegrityError):
            upsert_scholarship(db, _extract())

    def test_update_key_collision_recovers_to_owner(self):
        """Row found via fallback adopts a new u: key, but another committed
        row already holds it — the owner is the canonical identity holder."""
        existing = _row(portal_url="https://old.example.org/apply/merit")
        owner = _row(award_amount=999)
        db = FakeCatalogSession([existing])
        db.commit_errors = [IntegrityError("UPDATE", {}, Exception("duplicate key"))]
        db.on_rollback = lambda: db.rows.append(owner)

        s, action = upsert_scholarship(db, _extract(award_amount=7777))
        assert action == "updated" and s is owner
        assert owner.award_amount == 7777
