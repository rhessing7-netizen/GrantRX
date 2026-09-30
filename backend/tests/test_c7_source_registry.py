"""C7 source registry & scheduling tests.

Pure-function coverage for the health state machine, deterministic
scheduling, LLM-skip rules and key generation, plus MockTransport coverage
for durable validators/redirects. Real-DB import validation runs on the
isolated :5433 database via the E2E script (same pattern as C4/C6).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

import httpx
import pytest

from scrapers import source_registry as sr
from scrapers.fetch_policy import (
    OUTCOME_NOT_MODIFIED,
    OUTCOME_OK,
    OUTCOME_PERMANENT_HTTP,
    OUTCOME_ROBOTS_DENIED,
    OUTCOME_ROBOTS_UNAVAILABLE,
    OUTCOME_TIMEOUT,
    FetchPolicy,
    FetchResult,
    FetchSession,
)
from scrapers.sources import SourceConfig, load_sources

NOW = datetime(2026, 3, 15, 12, 0, 0)


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


def _res(outcome=OUTCOME_OK, **kw) -> FetchResult:
    return FetchResult(url="https://a.example.org/x", outcome=outcome, **kw)


def _cfg(name="Source A", url="https://a.example.org/x", **kw) -> SourceConfig:
    return SourceConfig(name=name, url=url, category=kw.pop("category", "national_association"), **kw)


class FakeDB:
    """Minimal session stub for sync_sources (helpers are patched)."""

    def __init__(self):
        self.rows: Dict[str, object] = {}
        self.commits = 0
        self.executed: List[dict] = []

    def add(self, row):
        self.rows[row.url] = row

    def commit(self):
        self.commits += 1

    def execute(self, sql, params=None):
        self.executed.append(params or {})
        return SimpleNamespace(rowcount=0)


def _patch_sync_helpers(monkeypatch, db: FakeDB):
    monkeypatch.setattr(sr, "_all_source_keys",
                        lambda d: {r.source_key for r in db.rows.values()})
    monkeypatch.setattr(sr, "_row_by_url", lambda d, u: db.rows.get(u))
    monkeypatch.setattr(
        sr, "_row_by_key",
        lambda d, k: next((r for r in db.rows.values() if r.source_key == k), None))


# ---------------------------------------------------------------------------
# Identity keys
# ---------------------------------------------------------------------------

class TestSourceKeys:
    def test_deterministic(self):
        assert sr.source_key_for("AOTF Scholarships", "https://x", set()) == \
            sr.source_key_for("AOTF Scholarships", "https://x", set())
        assert sr.source_key_for("AOTF Scholarships", "https://x", set()) == "aotf-scholarships"

    def test_collision_gets_url_hash_suffix(self):
        k1 = sr.source_key_for("Same Name", "https://a.example.org", set())
        k2 = sr.source_key_for("Same Name", "https://b.example.org", {k1})
        assert k1 != k2 and k2.startswith("same-name-")

    def test_empty_name_falls_back(self):
        assert sr.source_key_for("", "https://a.example.org", set()) == "source"


# ---------------------------------------------------------------------------
# Import / sync semantics (fake db)
# ---------------------------------------------------------------------------

class TestSyncSources:
    def test_import_creates_scheduled_rows(self, monkeypatch):
        db = FakeDB()
        _patch_sync_helpers(monkeypatch, db)
        out = sr.sync_sources(db, configs=[_cfg(), _cfg("Source B", "https://b.example.org")])
        assert out == {"configured": 2, "created": 2, "updated": 2}
        assert all(r.next_check_at is not None for r in db.rows.values())
        assert all(r.health == sr.HEALTH_UNKNOWN for r in db.rows.values())

    def test_import_idempotent_preserves_state(self, monkeypatch):
        db = FakeDB()
        _patch_sync_helpers(monkeypatch, db)
        cfgs = [_cfg()]
        sr.sync_sources(db, configs=cfgs)
        row = db.rows["https://a.example.org/x"]
        row.health = sr.HEALTH_HEALTHY
        row.enabled = False
        row.content_hash = "abc"
        out2 = sr.sync_sources(db, configs=cfgs)
        assert out2["created"] == 0 and len(db.rows) == 1
        # operational state survives re-import
        assert row.health == sr.HEALTH_HEALTHY
        assert row.enabled is False
        assert row.content_hash == "abc"

    def test_repaired_url_updates_same_source_in_place(self, monkeypatch):
        """E2 source maintenance: a configured source matched by source_key
        adopts the configured URL (same identity, history/health preserved)
        rather than orphaning the old row or creating a second source."""
        db = FakeDB()
        _patch_sync_helpers(monkeypatch, db)
        sr.sync_sources(db, configs=[_cfg(url="https://a.example.org/old")])
        row = db.rows["https://a.example.org/old"]
        row.health = sr.HEALTH_PERMANENT_NOT_FOUND
        out = sr.sync_sources(db, configs=[_cfg(url="https://a.example.org/new")])
        assert out["created"] == 0 and len(db.rows) == 1
        assert row.url == "https://a.example.org/new"
        assert row.health == sr.HEALTH_PERMANENT_NOT_FOUND  # health transition, not reset
        assert row.source_key == "source-a"

    def test_every_real_source_is_schedulable(self, monkeypatch):
        """Regression for the pre-C7 silent-coverage gap: every configured
        source (all 155, every category) must land in the registry with a
        next_check_at — no category can be dropped by a hard-coded weekday."""
        db = FakeDB()
        _patch_sync_helpers(monkeypatch, db)
        configs = load_sources()
        assert len(configs) >= 100  # the real configured universe
        sr.sync_sources(db, configs)
        cats = {c.category for c in configs}
        assert all(r.next_check_at is not None for r in db.rows.values())
        assert len(db.rows) == len({c.url for c in configs})
        assert {r.category for r in db.rows.values()} == cats

    def test_seed_import_filters_blanks(self):
        db = FakeDB()
        out = sr.sync_seeds(db, seeds=[{"url": "https://s.example.org", "name": "S"},
                                       {"url": "  "},
                                       {"name": "no url"}])
        assert out["seeds"] == 3
        # two blank/missing URLs skipped via early filter; row may also be
        # skipped when the URL already exists (rowcount=0)
        assert out["skipped_existing"] >= 2


# ---------------------------------------------------------------------------
# Due selection (pure mirror of the SQL predicate)
# ---------------------------------------------------------------------------

class TestDueSelection:
    def test_enabled_and_past_due(self):
        assert sr.is_due(_src(next_check_at=NOW - timedelta(hours=1)), NOW)
        assert sr.is_due(_src(next_check_at=None), NOW)

    def test_not_due_when_future(self):
        assert not sr.is_due(_src(next_check_at=NOW + timedelta(hours=1)), NOW)

    def test_disabled_never_due(self):
        assert not sr.is_due(_src(enabled=False, next_check_at=NOW - timedelta(days=1)), NOW)

    def test_unscheduled_healths_never_due(self):
        for h in (sr.HEALTH_NEEDS_URL_REVIEW, sr.HEALTH_RETIRED):
            assert not sr.is_due(_src(health=h, next_check_at=NOW - timedelta(days=1)), NOW)


# ---------------------------------------------------------------------------
# Targeted due selection (E4 source-key scoping)
# ---------------------------------------------------------------------------

class _RecordingQuery:
    """Query stub capturing filter calls so the SQL predicate is testable
    without a live database."""

    def __init__(self):
        self.filter_args: List[tuple] = []
        self.limit_value = None

    def filter(self, *args):
        self.filter_args.append(args)
        return self

    def order_by(self, *args):
        return self

    def limit(self, n):
        self.limit_value = n
        return self

    def all(self):
        return []


class _RecordingSession:
    def __init__(self):
        self.q = _RecordingQuery()

    def query(self, *args):
        return self.q


class TestDueSourceKeyFilter:
    def test_no_keys_leaves_baseline_predicate(self):
        db = _RecordingSession()
        sr.get_due_sources(db, now=NOW)
        assert len(db.q.filter_args) == 1  # only the enabled/due predicate

    def test_keys_add_in_filter(self):
        db = _RecordingSession()
        sr.get_due_sources(db, now=NOW, source_keys=["alpha", "beta"])
        assert len(db.q.filter_args) == 2
        clause = str(db.q.filter_args[1][0]).upper()
        assert "IN" in clause and "SOURCE_KEY" in clause

    def test_empty_list_is_unscoped(self):
        db = _RecordingSession()
        sr.get_due_sources(db, now=NOW, source_keys=[])
        assert len(db.q.filter_args) == 1

    def test_pipeline_forwards_keys(self, monkeypatch):
        from scrapers import runner

        seen = {}

        def fake_due(db, *, limit=None, now=None, source_keys=None):
            seen["source_keys"] = source_keys
            return []

        monkeypatch.setattr(sr, "get_due_sources", fake_due)
        asyncio.run(runner.run_due_sources_pipeline(
            db=_RecordingSession(), source_keys=["a", "b"]))
        assert seen["source_keys"] == ["a", "b"]

    def test_load_source_keys_parsing(self, tmp_path):
        from scrapers.runner import _load_source_keys

        assert _load_source_keys(None, None) is None
        assert _load_source_keys(" a , b ,", None) == ["a", "b"]
        jf = tmp_path / "keys.json"
        jf.write_text('["x", "y"]', encoding="utf-8")
        assert _load_source_keys(None, str(jf)) == ["x", "y"]
        tf = tmp_path / "keys.txt"
        tf.write_text("k1\nk2,k3\n", encoding="utf-8")
        assert _load_source_keys("z", str(tf)) == ["z", "k1", "k2", "k3"]


class TestDbSafeText:
    """E4: WIN1252 dev databases cannot store chars like U+02BB (ʻokina);
    unencodable text crashed the INSERT after the source was marked
    extracted, silently losing the record."""

    def test_utf8_passthrough(self):
        from scrapers.runner import _db_safe_text

        s = "Hawaiʻi Promise — sí"
        assert _db_safe_text(s, "utf-8") == s

    def test_cp1252_maps_okina(self):
        from scrapers.runner import _db_safe_text

        assert _db_safe_text("Hawaiʻi Promise", "cp1252") == "Hawai'i Promise"

    def test_cp1252_drops_unencodable(self):
        from scrapers.runner import _db_safe_text

        out = _db_safe_text("漢字 Scholarship", "cp1252")
        assert "漢" not in out and "Scholarship" in out
        out.encode("cp1252")  # must be encodable

    def test_list_recursion(self):
        from scrapers.runner import _db_safe_text

        assert _db_safe_text(["aʻb", 3], "cp1252") == ["a'b", 3]

    def test_cp1252_common_punctuation_kept(self):
        from scrapers.runner import _db_safe_text

        s = "“quoted” — dash…"  # all representable in cp1252
        assert _db_safe_text(s, "cp1252") == s

    def test_cp1252_only_touches_unencodable_chars(self):
        """E4.5: NFKC must not rewrite storable chars (½ -> '12' corruption)."""
        from scrapers.runner import _db_safe_text

        s = "Hawaiʻi award $1½ million™ ²"
        assert _db_safe_text(s, "cp1252") == "Hawai'i award $1½ million™ ²"

    def test_cp1252_compat_form_used_only_when_encodable(self):
        from scrapers.runner import _db_safe_text

        # U+FB01 'ﬁ' ligature is not cp1252; its NFKC form 'fi' is.
        assert _db_safe_text("ﬁnancial aid", "cp1252") == "financial aid"

    def test_utf8_never_modified_even_with_rare_chars(self):
        from scrapers.runner import _db_safe_text

        s = "ﬁ ½ ʻ 漢字 — 😀"
        assert _db_safe_text(s, "utf-8") is s

    def test_unknown_encoding_leaves_text_untouched(self):
        from scrapers.runner import _db_safe_text

        assert _db_safe_text("Hawaiʻi", "no-such-codec") == "Hawaiʻi"

    def test_db_encoding_detection(self):
        from types import SimpleNamespace as NS

        from scrapers.runner import _db_encoding

        def db_with(enc):
            driver = NS(info=NS(encoding=enc))
            return NS(connection=lambda: NS(driver_connection=driver))

        assert _db_encoding(db_with("cp1252")) == "cp1252"
        assert _db_encoding(db_with("UTF8")) == "utf-8"
        assert _db_encoding(db_with("bogus")) == "utf-8"
        assert _db_encoding(db_with(None)) == "utf-8"

    def test_upsert_on_utf8_connection_persists_text_verbatim(self):
        from unittest.mock import MagicMock, patch

        from scrapers.runner import upsert_scholarship
        from scrapers.schema import ScholarshipExtract

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        added = []
        db.add.side_effect = added.append
        ex = ScholarshipExtract(title="Hawaiʻi ½ Promise Scholarship", provider="UH ﬁ",
                                portal_url="https://example.edu/hawaii-promise")
        with patch("scrapers.runner._db_encoding", return_value="utf-8"), \
                patch("scrapers.runner._db_safe_text") as sanitizer:
            upsert_scholarship(db, ex)
        sanitizer.assert_not_called()
        assert added[0].title == "Hawaiʻi ½ Promise Scholarship"
        assert added[0].provider == "UH ﬁ"


# ---------------------------------------------------------------------------
# Health state machine
# ---------------------------------------------------------------------------

class TestHealthTransitions:
    def test_ok_is_healthy(self):
        assert sr.classify_health(sr.HEALTH_UNKNOWN, _res()) == sr.HEALTH_HEALTHY

    def test_ok_with_redirect_is_moved(self):
        r = _res(final_url="https://b.example.org/x", permanent_redirect=True)
        assert sr.classify_health(sr.HEALTH_UNKNOWN, r) == sr.HEALTH_REDIRECTED

    def test_304_preserves_health(self):
        r = _res(outcome=OUTCOME_NOT_MODIFIED, http_status=304)
        assert sr.classify_health(sr.HEALTH_REDIRECTED, r) == sr.HEALTH_REDIRECTED

    def test_first_permanent_http(self):
        r = _res(outcome=OUTCOME_PERMANENT_HTTP, http_status=404)
        assert sr.classify_health(sr.HEALTH_HEALTHY, r) == sr.HEALTH_PERMANENT_NOT_FOUND

    def test_second_permanent_needs_review(self):
        """A 404 means the URL is gone — not that the provider died — so a
        *repeat* permanent failure escalates to a human review queue, never
        to retirement."""
        r = _res(outcome=OUTCOME_PERMANENT_HTTP, http_status=404)
        assert sr.classify_health(sr.HEALTH_PERMANENT_NOT_FOUND, r) == sr.HEALTH_NEEDS_URL_REVIEW

    def test_transient_never_becomes_permanent(self):
        r = _res(outcome=OUTCOME_TIMEOUT)
        h = sr.classify_health(sr.HEALTH_HEALTHY, r)
        assert h == sr.HEALTH_TRANSIENT
        # many consecutive transient failures stay transient — never quarantine
        src = _src(health=h)
        for _ in range(10):
            h = sr.apply_check(src, r, NOW)
            assert h == sr.HEALTH_TRANSIENT

    def test_robots_states(self):
        assert sr.classify_health(sr.HEALTH_HEALTHY, _res(outcome=OUTCOME_ROBOTS_DENIED)) \
            == sr.HEALTH_ROBOTS_DENIED
        assert sr.classify_health(sr.HEALTH_HEALTHY, _res(outcome=OUTCOME_ROBOTS_UNAVAILABLE)) \
            == sr.HEALTH_ROBOTS_UNAVAILABLE


# ---------------------------------------------------------------------------
# Deterministic scheduling
# ---------------------------------------------------------------------------

class TestScheduling:
    def test_healthy_gets_base_interval(self):
        src = _src()
        sr.apply_check(src, _res(), NOW)
        assert src.next_check_at == NOW + timedelta(days=7)

    def test_transient_backoff_bounded_and_holds(self):
        src = _src()
        r = _res(outcome=OUTCOME_TIMEOUT)
        expected = [timedelta(hours=1), timedelta(hours=6), timedelta(hours=24)]
        for exp in expected:
            sr.apply_check(src, r, NOW)
            assert src.next_check_at == NOW + exp
        for _ in range(3):
            sr.apply_check(src, r, NOW)
            assert src.next_check_at == NOW + timedelta(hours=72)

    def test_robots_rechecks_weekly_without_failure_accrual(self):
        src = _src()
        src.consecutive_failures = 0
        sr.apply_check(src, _res(outcome=OUTCOME_ROBOTS_DENIED), NOW)
        assert src.health == sr.HEALTH_ROBOTS_DENIED
        assert src.consecutive_failures == 0
        assert src.next_check_at == NOW + timedelta(days=7)

    def test_permanent_escalates_to_review_unscheduled(self):
        src = _src(health=sr.HEALTH_PERMANENT_NOT_FOUND)
        sr.apply_check(src, _res(outcome=OUTCOME_PERMANENT_HTTP, http_status=410), NOW)
        assert src.health == sr.HEALTH_NEEDS_URL_REVIEW
        assert src.next_check_at is None

    def test_unchanged_pages_slow_down(self):
        src = _src()
        r = _res(content_hash="h1")
        # first fetch: hash recorded, streak 0 -> base interval
        sr.apply_check(src, r, NOW)
        assert src.next_check_at == NOW + timedelta(days=7)
        for i in range(1, 4):
            sr.apply_check(src, r, NOW)
            assert src.next_check_at == NOW + timedelta(days=7)
        sr.apply_check(src, r, NOW)  # streak hits 4 -> 2x
        assert src.next_check_at == NOW + timedelta(days=14)
        for _ in range(4):
            sr.apply_check(src, r, NOW)
        assert src.next_check_at == NOW + timedelta(days=28)  # streak 8 -> 4x capped

    def test_changed_content_resets_streak(self):
        src = _src(consecutive_unchanged=5)
        sr.apply_check(src, _res(content_hash="new"), NOW)
        assert src.consecutive_unchanged == 0
        assert src.next_check_at == NOW + timedelta(days=7)

    def test_peak_month_shortens_interval(self):
        src = _src(peak_months=[3], peak_interval_seconds=3 * 86400)
        sr.apply_check(src, _res(content_hash="x"), NOW)
        assert src.next_check_at == NOW + timedelta(days=3)
        src2 = _src(peak_months=[6], peak_interval_seconds=3 * 86400)
        sr.apply_check(src2, _res(content_hash="x"), NOW)
        assert src2.next_check_at == NOW + timedelta(days=7)

    def test_durable_validators_and_hash_persisted(self):
        src = _src()
        sr.apply_check(src, _res(content_hash="h", etag='"e1"', last_modified="Mon"), NOW)
        assert src.content_hash == "h"
        assert src.etag == '"e1"' and src.last_modified == "Mon"
        assert src.checks_total == 1

    def test_diagnostics_bounded(self):
        src = _src()
        sr.apply_check(src, _res(outcome=OUTCOME_TIMEOUT, error="ConnectTimeout"), NOW)
        assert src.last_error == "ConnectTimeout"
        assert len(src.last_error or "") <= 500


# ---------------------------------------------------------------------------
# LLM-skip decision
# ---------------------------------------------------------------------------

class TestShouldExtract:
    def test_never_extracted_extracts(self):
        do, why = sr.should_extract(_src(), _res(text="<p>x</p>", content_hash="h"), NOW)
        assert do and why == "never_extracted"

    def test_changed_content_extracts(self):
        src = _src(extracted_hash="old", last_extracted_at=NOW)
        do, why = sr.should_extract(src, _res(text="<p>x</p>", content_hash="new"), NOW)
        assert do and why == "changed"

    def test_unchanged_skips(self):
        src = _src(extracted_hash="h", last_extracted_at=NOW)
        do, why = sr.should_extract(src, _res(text="<p>x</p>", content_hash="h"), NOW)
        assert not do and why == "unchanged"

    def test_forced_reextract_after_window(self):
        src = _src(extracted_hash="h",
                   last_extracted_at=NOW - timedelta(days=31))
        do, why = sr.should_extract(src, _res(text="<p>x</p>", content_hash="h"), NOW)
        assert do and why == "forced_refresh"

    def test_304_never_extracts_body(self):
        do, why = sr.should_extract(_src(), _res(outcome=OUTCOME_NOT_MODIFIED), NOW)
        assert not do and why == "not_modified"

    def test_failed_check_never_extracts(self):
        do, why = sr.should_extract(_src(), _res(outcome=OUTCOME_TIMEOUT), NOW)
        assert not do and why == "no_content"

    def test_extraction_pending(self):
        assert sr.extraction_pending(_src(content_hash="h", extracted_hash=None))
        assert not sr.extraction_pending(_src(content_hash="h", extracted_hash="h"))


# ---------------------------------------------------------------------------
# Fetch-level integration (MockTransport): validators, 304, redirects
# ---------------------------------------------------------------------------

class _Server:
    def __init__(self):
        self.responses: Dict[Tuple[str, str], object] = {}
        self.requests: List[httpx.Request] = []

    def add(self, method: str, url: str, resp):
        self.responses[(method, url)] = resp

    def page(self, url: str, status=200, body="<html><body>x</body></html>", headers=None):
        self.add("GET", url, httpx.Response(status, text=body, headers=headers or {}))

    def headers_for(self, url: str) -> dict:
        for req in reversed(self.requests):
            if str(req.url) == url:
                return {k.lower(): v for k, v in req.headers.items()}
        return {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        resp = self.responses.get((request.method, str(request.url)))
        if isinstance(resp, Exception):
            raise resp
        return resp if resp is not None else httpx.Response(404, text="nf")


def _session(server: _Server) -> FetchSession:
    policy = FetchPolicy(min_interval=0.0, max_retries=0)
    client = httpx.AsyncClient(transport=httpx.MockTransport(server.handler),
                               follow_redirects=True)
    return FetchSession(policy=policy, client=client)


class TestDurableValidators:
    def test_primed_validators_send_conditional_headers(self):
        server = _Server()
        server.page("https://h.example.org/robots.txt", status=404, body="")
        server.page("https://h.example.org/p", status=304, body="")
        s = _session(server)
        s.prime_validators("https://h.example.org/p", '"etag-1"', "Wed, 01 Jan 2020")
        res = asyncio.run(s.get("https://h.example.org/p"))
        assert res.outcome == OUTCOME_NOT_MODIFIED
        page_headers = server.headers_for("https://h.example.org/p")
        assert page_headers.get("if-none-match") == '"etag-1"'
        assert page_headers.get("if-modified-since") == "Wed, 01 Jan 2020"

    def test_unconditional_get_sends_no_validators(self):
        server = _Server()
        server.page("https://h.example.org/robots.txt", status=404, body="")
        server.page("https://h.example.org/p", status=200, body="<p>new</p>")
        s = _session(server)
        s.prime_validators("https://h.example.org/p", '"etag-1"', None)
        res = asyncio.run(s.get("https://h.example.org/p", conditional=False))
        assert res.outcome == OUTCOME_OK
        assert "if-none-match" not in server.headers_for("https://h.example.org/p")


class TestRedirects:
    def test_redirect_capture_and_health(self):
        server = _Server()
        server.page("https://h.example.org/robots.txt", status=404, body="")
        server.add("GET", "https://h.example.org/old",
                   httpx.Response(301, headers={"Location": "https://h.example.org/new"}))
        server.page("https://h.example.org/new", status=200, body="<p>new</p>")
        s = _session(server)
        res = asyncio.run(s.get("https://h.example.org/old"))
        assert res.outcome == OUTCOME_OK
        assert res.final_url == "https://h.example.org/new"
        assert res.permanent_redirect is True
        assert sr.classify_health(sr.HEALTH_UNKNOWN, res) == sr.HEALTH_REDIRECTED
