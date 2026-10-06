"""Connection-pool hardening regression tests.

Hosted Postgres poolers (e.g. Supabase's session pooler) silently reap idle
client connections; without pre-ping a pooled dead socket surfaces as a hung
query. These tests pin the engine's stale-connection defenses.
"""

import importlib

from sqlalchemy import pool as sa_pool

from app import database


def test_engine_uses_queue_pool():
    assert isinstance(database.engine.pool, sa_pool.QueuePool)


def test_engine_pre_ping_discards_stale_connections():
    assert database.engine.pool._pre_ping is True


def test_engine_recycles_connections_before_pooler_idle_timeout():
    assert database.engine.pool._recycle == 300


def test_postgres_url_gets_tcp_keepalives():
    """The default Postgres DATABASE_URL must carry libpq keepalive params."""
    assert database.DATABASE_URL.startswith("postgresql")
    args = database.ENGINE_KWARGS["connect_args"]
    assert args["keepalives"] == 1
    assert args["keepalives_idle"] > 0
    assert args["keepalives_interval"] > 0
    assert args["keepalives_count"] > 0


def test_keepalives_skipped_for_non_postgres_urls(monkeypatch):
    """connect_args keepalives are libpq-only — never applied to sqlite etc."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///pytest-nonpg.db")
    importlib.reload(database)
    try:
        assert "connect_args" not in database.ENGINE_KWARGS
    finally:
        monkeypatch.undo()
        importlib.reload(database)
