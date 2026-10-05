"""Regression coverage for scripts/sync_catalog_to_staging.py.

The staging sync failed once because psycopg re-encoded a jsonb-sourced
Python list as a PostgreSQL array literal ({PharmD,...}), which a jsonb
column rejects. These tests pin the type-safe adaptation and the atomic
single-transaction destination write.
"""

import datetime
import json
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psycopg.types.json import Jsonb

from scripts import sync_catalog_to_staging as sync


# ---------------------------------------------------------------------------
# Fakes — no real database needed
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows=None, one=None, desc=()):
        self._rows = rows or []
        self._one = one
        self.description = desc

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one


class _Col:
    def __init__(self, name):
        self.name = name


class _FakeTx:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.tx_entered = True
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.committed = True
        else:
            self.conn.rolled_back = True
        return False


class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def executemany(self, sql, rows):
        # materialize so generator-side adapters are exercised
        rows = list(rows)
        self.conn.executemany_calls.append((sql, rows))
        if self.conn.fail_on_table and self.conn.fail_on_table in sql:
            raise RuntimeError(f"boom on {self.conn.fail_on_table}")


class _FakeConn:
    """Minimal psycopg.Connection stand-in for source and target."""

    def __init__(self, url, *, scholarships=830, fail_on_table=None):
        self.url = url
        self.scholarships = scholarships
        self.fail_on_table = fail_on_table
        self.queries = []
        self.executemany_calls = []
        self.tx_entered = False
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def close(self):
        pass

    def transaction(self):
        return _FakeTx(self)

    def cursor(self):
        return _FakeCursor(self)

    def execute(self, sql, params=None):
        self.queries.append(sql)
        if "information_schema" in sql:
            return _FakeResult(rows=[])  # pretend no jsonb cols (tested separately)
        if "COUNT(*)" in sql:
            for t in sync.CATALOG_TABLES:
                if f"FROM {t}" in sql:
                    n = self.scholarships if t == "scholarships" else 0
                    return _FakeResult(one=(n,))
        if "SELECT * FROM" in sql and "LIMIT 0" in sql:
            return _FakeResult(desc=[_Col("id")])
        if "SELECT * FROM" in sql:
            return _FakeResult(rows=[(uuid.uuid4(),)])
        return _FakeResult()


def _fake_connect_factory(recorded, *, source_map=None, fail_on_table=None):
    def _connect(url, **kwargs):
        recorded.append(url)
        if source_map and url in source_map:
            return source_map[url]
        return _FakeConn(url, fail_on_table=fail_on_table)

    return _connect


# ---------------------------------------------------------------------------
# _adapt_row — JSONB-safe value adaptation
# ---------------------------------------------------------------------------


class TestJsonbAdaptation:
    COLS = ["id", "target_credentials", "verified_fields", "tags"]

    def test_list_wrapped_as_jsonb(self):
        row = (uuid.uuid4(), ["PharmD"], {"a": 1}, ["x", "y"])
        out = sync._adapt_row(row, self.COLS, {"target_credentials"})
        assert isinstance(out[1], Jsonb) and out[1].obj == ["PharmD"]

    def test_dict_wrapped_as_jsonb(self):
        out = sync._adapt_row((1, None, {"k": [1, 2]}, None), self.COLS,
                              {"verified_fields"})
        assert isinstance(out[2], Jsonb) and out[2].obj == {"k": [1, 2]}
        assert json.loads(json.dumps(out[2].obj)) == {"k": [1, 2]}

    def test_none_stays_null_not_json_null(self):
        out = sync._adapt_row((1, None, None, None), self.COLS,
                              {"target_credentials", "verified_fields"})
        assert out[1] is None and out[2] is None

    def test_multiple_jsonb_columns(self):
        out = sync._adapt_row((1, ["A"], {"b": True}, ["z"]), self.COLS,
                              {"target_credentials", "verified_fields"})
        assert isinstance(out[1], Jsonb) and isinstance(out[2], Jsonb)

    def test_real_array_column_not_wrapped(self):
        # 'tags' models a genuine text[] column — lists must stay bare so
        # psycopg adapts them to PostgreSQL arrays, never Jsonb.
        out = sync._adapt_row((1, ["A"], None, ["x", "y"]), self.COLS,
                              {"target_credentials"})
        assert out[3] == ["x", "y"] and not isinstance(out[3], Jsonb)

    def test_uuid_and_scalars_pass_through(self):
        u = uuid.uuid4()
        d = datetime.date(2026, 10, 4)
        out = sync._adapt_row((u, 42, d, "txt"), self.COLS, set())
        assert out == (u, 42, d, "txt")


class TestJsonbColumnDetection:
    def test_detects_json_and_jsonb_only(self):
        class Src:
            def execute(self, sql, params=None):
                assert "json" in sql
                return _FakeResult(rows=[("target_credentials",), ("peak_months",)])

        cols = sync._jsonb_columns(Src(), "catalog_sources")
        assert cols == {"target_credentials", "peak_months"}


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


class TestGuards:
    def test_target_required(self, monkeypatch):
        monkeypatch.delenv("TARGET_DATABASE_URL", raising=False)
        with pytest.raises(SystemExit):
            sync._target(required=True)

    def test_target_rejects_localhost_and_5432(self, monkeypatch):
        for bad in (
            "postgresql://u:p@127.0.0.1:6543/x",
            "postgresql://u:p@localhost:6543/x",
            "postgresql://u:p@aws-0-us-east-2.pooler.supabase.com:5432/postgres",
        ):
            monkeypatch.setenv("TARGET_DATABASE_URL", bad)
            with pytest.raises(SystemExit):
                sync._target()

    def test_target_rejects_frozen_catalog(self, monkeypatch):
        monkeypatch.setenv(
            "TARGET_DATABASE_URL",
            "postgresql://grantrx:grantrx@127.0.0.1:5433/grantrx",
        )
        with pytest.raises(SystemExit):
            sync._target()

    def test_remote_target_accepted(self, monkeypatch):
        good = "postgresql://postgres.ref:pw@aws-0-us-east-2.pooler.supabase.com:6543/postgres"
        monkeypatch.setenv("TARGET_DATABASE_URL", good)
        assert sync._target() == good

    def test_source_defaults_to_local_catalog(self, monkeypatch):
        monkeypatch.delenv("SOURCE_DATABASE_URL", raising=False)
        assert sync.DEFAULT_SOURCE.endswith("127.0.0.1:5433/grantrx")

    def test_production_never_implicit(self, monkeypatch):
        # No TARGET_DATABASE_URL -> script must refuse; nothing ever derives a
        # remote target from DATABASE_URL or the local source.
        monkeypatch.delenv("TARGET_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@prod.example.com/db")
        with pytest.raises(SystemExit):
            sync._target()


# ---------------------------------------------------------------------------
# Ordering, dry-run, atomicity
# ---------------------------------------------------------------------------


def test_insert_order_parents_before_children():
    assert set(sync.INSERT_ORDER) == set(sync.CATALOG_TABLES)
    assert sync.INSERT_ORDER.index("scholarships") < sync.INSERT_ORDER.index(
        "scholarship_tracks"
    )


def test_dry_run_never_connects_to_target(monkeypatch):
    monkeypatch.delenv("TARGET_DATABASE_URL", raising=False)
    recorded = []
    monkeypatch.setattr(sync.psycopg, "connect", _fake_connect_factory(recorded))
    monkeypatch.setattr(sys, "argv", ["prog", "--dry-run"])
    assert sync.main() == 0
    # exactly one connection: the local source only
    assert recorded == [sync.DEFAULT_SOURCE]


def test_failed_insert_rolls_back_all_catalog_changes(monkeypatch):
    monkeypatch.setenv("TARGET_DATABASE_URL",
                       "postgresql://u:p@remote-pooler.example.com:6543/postgres")
    recorded = []
    target = _FakeConn("tgt", fail_on_table="scholarships")
    source_map = {sync.DEFAULT_SOURCE: _FakeConn(sync.DEFAULT_SOURCE)}
    monkeypatch.setattr(sync.psycopg, "connect",
                        _fake_connect_factory(recorded, source_map=source_map))
    # return our failing target for the non-source URL
    orig = sync.psycopg.connect

    def _connect(url, **kw):
        recorded.append(url)
        if url == sync.DEFAULT_SOURCE:
            return source_map[url]
        return target

    monkeypatch.setattr(sync.psycopg, "connect", _connect)
    monkeypatch.setattr(sys, "argv", ["prog"])
    with pytest.raises(RuntimeError, match="boom on scholarships"):
        sync.main()
    # all four TRUNCATEs ran inside one transaction, insert failed, rolled back
    assert target.tx_entered and target.rolled_back and not target.committed
    truncates = [q for q in target.queries if q.startswith("TRUNCATE")]
    assert len(truncates) == 4


def test_success_path_commits_once(monkeypatch):
    recorded = []
    target = _FakeConn("tgt")
    source_map = {sync.DEFAULT_SOURCE: _FakeConn(sync.DEFAULT_SOURCE)}

    def _connect(url, **kw):
        recorded.append(url)
        return source_map.get(url, target)

    monkeypatch.setattr(sync.psycopg, "connect", _connect)
    monkeypatch.setenv("TARGET_DATABASE_URL",
                       "postgresql://u:p@remote-pooler.example.com:6543/postgres")
    monkeypatch.setattr(sys, "argv", ["prog"])
    assert sync.main() == 0
    assert target.committed and not target.rolled_back and target.tx_entered


def test_source_fingerprint_guard_aborts_wrong_count(monkeypatch):
    monkeypatch.delenv("TARGET_DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["prog", "--dry-run"])
    monkeypatch.setattr(
        sync.psycopg, "connect",
        lambda url, **kw: _FakeConn(url, scholarships=829),
    )
    with pytest.raises(SystemExit):
        sync.main()
