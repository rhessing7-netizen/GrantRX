-- Migration 025: durable source registry & scheduling (Catalog Batch C7).
--
-- One authoritative registry for configured catalog sources: identity,
-- fetch mode, deterministic scheduling, durable health, durable HTTP
-- validators (ETag/Last-Modified) and content hashes so unchanged pages can
-- skip LLM extraction across runs. crawler_seeds remains the distinct
-- discovery queue (reconciled by explicit scheduling, not merged).
--
-- Additive only: creates a new table, no changes to existing tables.

CREATE TABLE IF NOT EXISTS catalog_sources (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- stable human identity; survives URL moves (a moved page keeps its key)
    source_key              TEXT NOT NULL,
    name                    TEXT NOT NULL,
    url                     TEXT NOT NULL,
    -- configured metadata (mirrors sources.json / SourceConfig)
    category                TEXT NOT NULL DEFAULT 'national_association',
    primary_discipline      TEXT NOT NULL DEFAULT 'any',
    target_credentials      JSONB NOT NULL DEFAULT '[]'::jsonb,
    state_restriction       TEXT,
    scraper_type            TEXT NOT NULL DEFAULT 'deterministic',
    enabled                 BOOLEAN NOT NULL DEFAULT TRUE,
    -- deterministic scheduling
    check_interval_seconds  INTEGER NOT NULL DEFAULT 604800,  -- base interval (7d)
    peak_months             JSONB,                            -- e.g. [1,2,3]; optional season
    peak_interval_seconds   INTEGER,                          -- shorter interval in peak months
    next_check_at           TIMESTAMPTZ,
    -- durable health (see scrapers/source_registry.py for the state machine)
    health                  TEXT NOT NULL DEFAULT 'unknown',
    consecutive_failures    INTEGER NOT NULL DEFAULT 0,
    consecutive_unchanged   INTEGER NOT NULL DEFAULT 0,
    last_error              TEXT,
    last_resolved_url       TEXT,                             -- final URL after redirects
    -- check history
    last_attempted_at       TIMESTAMPTZ,
    last_fetch_ok_at        TIMESTAMPTZ,
    last_extracted_at       TIMESTAMPTZ,
    last_check_outcome      TEXT,
    last_http_status        INTEGER,
    -- durable fetch metadata (promoted from C6's in-run state)
    content_hash            TEXT,   -- hash of last fetched page content
    extracted_hash          TEXT,   -- hash of content at last successful extraction
    etag                    TEXT,
    last_modified           TEXT,
    -- bounded observability counters
    checks_total            INTEGER NOT NULL DEFAULT 0,
    extractions_total       INTEGER NOT NULL DEFAULT 0,
    skips_total             INTEGER NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One row per configured source identity and per configured URL.
CREATE UNIQUE INDEX IF NOT EXISTS idx_catalog_sources_key
    ON catalog_sources (source_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_catalog_sources_url
    ON catalog_sources (url);

-- Due-source selection: everything enabled whose check is due.
CREATE INDEX IF NOT EXISTS idx_catalog_sources_due
    ON catalog_sources (enabled, next_check_at);
CREATE INDEX IF NOT EXISTS idx_catalog_sources_health
    ON catalog_sources (health);
