"""C2 crawl-path parity & heuristic-safety regression tests.

Covers:
  - independent verification attached on the crawler path (same trust boundary
    as known-source ingestion — the extractor cannot self-certify);
  - no crawler page-prose state/metro hard restrictions;
  - explicitly extracted geography survives;
  - per-seed success/failure accounting and bounded diagnostics;
  - correct hub-origin attribution;
  - safe refresh of known crawl-discovered opportunities (dedup via upsert).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

import scrapers.runner as runner
from scrapers.crawler import CrawlCandidate, ScholarshipCrawler
from scrapers.schema import ScholarshipExtract


# ---------------------------------------------------------------------------
# Fakes / helpers
# ---------------------------------------------------------------------------

def _extract(**kw) -> ScholarshipExtract:
    defaults = dict(
        title="C2 Merit Grant",
        provider="C2 Provider",
        portal_url="https://source.example.com/award",
        award_amount=5000,
        deadline="2027-03-01",
    )
    defaults.update(kw)
    return ScholarshipExtract(**defaults)


class _FakeStats:
    def __init__(self, summary):
        self._s = summary
        # Attribute access used by the runner's summary log line.
        self.pages_crawled = summary.get("pages_crawled", 0)
        self.candidates_found = summary.get("candidates_found", 0)

    def summary(self):
        return self._s


def _candidate(url="https://source.example.com/award", html="<html>hi</html>", **kw):
    return CrawlCandidate(
        url=url, title=kw.get("page_title", "Award Page"), html=html,
        text=kw.get("text", ""), relevance_score=5,
        seed_url=kw.get("seed_url", url), depth=1,
        state_restriction=kw.get("state_restriction"),
        regional_keywords=kw.get("regional_keywords", []),
    )


def _run_crawl_pipeline(candidates, extracts, db, seed_summary=None):
    """Run the real run_crawl_pipeline with crawler/LLM/DB/HTTP fully mocked."""
    extract_iter = iter(extracts)
    stats = _FakeStats(seed_summary or {
        "pages_crawled": len(candidates), "errors": 0,
        "candidates_found": len(candidates), "links_followed": 0,
        "links_rejected": 0, "domains_visited": [], "discovered_hubs": [],
        "discovered_hub_origins": {}, "seed_results": {},
    })

    class _Crawler:
        def __init__(self, seeds, **kw):
            pass

        async def crawl(self):
            return candidates

        def get_stats(self):
            return stats

    async def _fake_llm(html, url, **kw):
        # C5 list contract: the page yields exactly this one opportunity.
        from scrapers.llm_parser import LLMExtraction
        return LLMExtraction(extracts=[next(extract_iter)])

    async def _fake_verify(url, **kw):
        return url, True

    with patch("scrapers.crawler.ScholarshipCrawler", _Crawler), \
         patch("scrapers.llm_parser.extract_opportunities_with_llm", _fake_llm), \
         patch.object(runner, "_verify_portal_url", _fake_verify), \
         patch.object(runner, "archive_expired", lambda db: 0), \
         patch("app.database.SessionLocal", return_value=db):
        import asyncio
        return asyncio.run(
            runner.run_crawl_pipeline(["https://seed.example.com"], persist=True)
        )


def _make_db():
    """Session fake whose scholarship store persists across calls.

    Uses the shared conftest session so identity lookups are evaluated for
    real (a MagicMock's .filter() chain would return truthy phantoms and
    mask whether the upsert found the right row).
    """
    from tests.conftest import FakeCatalogSession

    db = FakeCatalogSession()
    db._store = db.rows
    return db


# ---------------------------------------------------------------------------
# 1. Verification parity on the crawl path
# ---------------------------------------------------------------------------

class TestCrawlVerificationParity:
    def test_supported_facts_verify_on_crawl_path(self):
        html = (
            "<html><body><h1>C2 Merit Grant</h1>"
            "<p>Award: $5,000. Deadline: March 1, 2027.</p></body></html>"
        )
        db = _make_db()
        _run_crawl_pipeline(
            [_candidate(html=html)],
            [_extract()],
            db,
        )
        row = db._store[0]
        assert row.verification_status == "verified"
        assert row.verified_at is not None
        assert row.verified_fields["title"] == "verified"
        assert row.verified_fields["award_amount"] == "verified"

    def test_unsupported_facts_mark_needs_review(self):
        html = "<html><body><h1>C2 Merit Grant</h1><p>No details here.</p></body></html>"
        db = _make_db()
        _run_crawl_pipeline(
            [_candidate(html=html)],
            [_extract()],
            db,
        )
        row = db._store[0]
        assert row.verification_status == "needs_review"
        assert row.verified_at is None

    def test_extractor_cannot_self_certify(self):
        """Even if a stray 'verified' attr lands on the extract object, the
        downstream verifier recomputes from source evidence."""
        html = "<html><body><h1>C2 Merit Grant</h1></body></html>"
        extract = _extract()
        object.__setattr__(extract, "verification_status", "verified")
        db = _make_db()
        _run_crawl_pipeline([_candidate(html=html)], [extract], db)
        assert db._store[0].verification_status == "needs_review"

    def test_unasserted_fields_not_marked_verified(self):
        html = "<html><body><h1>C2 Merit Grant</h1></body></html>"
        extract = _extract(award_amount=None, deadline=None)
        db = _make_db()
        _run_crawl_pipeline([_candidate(html=html)], [extract], db)
        row = db._store[0]
        assert row.award_amount is None
        assert row.verified_fields["award_amount"] == "not_asserted"
        assert row.verified_fields["deadline"] == "not_asserted"


# ---------------------------------------------------------------------------
# 2. Geographic heuristic safety
# ---------------------------------------------------------------------------

class TestGeographicSafety:
    COLLISION_PROSE = (
        "Applicants will be notified by mail. Cook county fair volunteers "
        "welcome. Orange you glad to learn about the lake district? "
        "Scholarship award for students."
    )

    def test_prose_does_not_create_metro_or_state_restrictions(self):
        html = f"<html><body><h1>C2 Merit Grant</h1><p>{self.COLLISION_PROSE}</p></body></html>"
        # Simulate what the crawler would have detected from this prose.
        cand = _candidate(html=html, state_restriction="OH",
                          regional_keywords=["metro:Chicago-Naperville-Elgin", "will"])
        db = _make_db()
        _run_crawl_pipeline([cand], [_extract()], db)
        row = db._store[0]
        assert row.metro_restrictions == []
        assert row.state_restrictions == []

    def test_extracted_geography_survives(self):
        html = "<html><body><h1>C2 Merit Grant</h1><p>Texas residents only. $5,000. March 1, 2027.</p></body></html>"
        extract = _extract(state_restrictions=["TX"])
        db = _make_db()
        _run_crawl_pipeline([_candidate(html=html)], [extract], db)
        assert db._store[0].state_restrictions == ["TX"]


# ---------------------------------------------------------------------------
# 3. Safe refresh of known crawl-discovered opportunities
# ---------------------------------------------------------------------------

class TestRefresh:
    def test_second_crawl_updates_in_place(self):
        html_v1 = "<html><body><h1>C2 Merit Grant</h1><p>Award $5,000. March 1, 2027.</p></body></html>"
        html_v2 = "<html><body><h1>C2 Merit Grant</h1><p>Award $7,500. March 1, 2027.</p></body></html>"
        db = _make_db()
        _run_crawl_pipeline([_candidate(html=html_v1)], [_extract()], db)
        assert len(db._store) == 1
        assert db._store[0].award_amount == 5000

        _run_crawl_pipeline(
            [_candidate(html=html_v2)],
            [_extract(award_amount=7500)],
            db,
        )
        assert len(db._store) == 1, "refresh must not create a duplicate row"
        assert db._store[0].award_amount == 7500

    def test_refresh_recomputes_verification(self):
        html_v1 = "<html><body><h1>C2 Merit Grant</h1><p>Award $5,000. March 1, 2027.</p></body></html>"
        html_v2 = "<html><body><h1>C2 Merit Grant</h1><p>Details removed.</p></body></html>"
        db = _make_db()
        _run_crawl_pipeline([_candidate(html=html_v1)], [_extract()], db)
        assert db._store[0].verification_status == "verified"

        _run_crawl_pipeline([_candidate(html=html_v2)], [_extract()], db)
        assert db._store[0].verification_status == "needs_review"
        assert db._store[0].verified_at is None


# ---------------------------------------------------------------------------
# 4. Per-seed outcome accounting + hub attribution (queue driver)
# ---------------------------------------------------------------------------

def _seed(seed_id, url):
    return {
        "id": seed_id, "url": url, "category": "test", "priority": 5,
        "status": "queued", "last_crawled_at": None, "error_count": 0,
    }


class TestDynamicQueueAccounting:
    def _run_queue(self, seed_batch, crawl_summary, marks, enqueues):
        async def _fake_crawl(seeds, **kw):
            return crawl_summary

        with patch.object(runner, "run_crawl_pipeline", _fake_crawl), \
             patch("scrapers.seed_queue.get_next_seed_batch", return_value=seed_batch), \
             patch("scrapers.seed_queue.mark_seed_crawled",
                   lambda db, sid, success, error=None: marks.append((sid, success, error))), \
             patch("scrapers.seed_queue.enqueue_discovered_seeds",
                   lambda db, urls, parent_url, detected_category: enqueues.append((urls, parent_url)) or len(urls)), \
             patch("app.database.SessionLocal", return_value=MagicMock()):
            import asyncio
            return asyncio.run(
                runner.run_dynamic_queue_pipeline(queue_limit=20)
            )

    def test_per_seed_outcomes_isolated(self):
        seeds = [
            _seed("sa", "https://a.example.com"),
            _seed("sb", "https://b.example.com"),
            _seed("sc", "https://c.example.com"),
        ]
        summary = {
            "errors": 3,  # batch-wide errors exist but must not contaminate
            "seed_results": {
                "https://a.example.com": {"success": True, "error": ""},
                "https://b.example.com": {"success": False, "error": "HTTP 500"},
                # Seed C succeeded even though irrelevant child pages failed.
                "https://c.example.com": {"success": True, "error": ""},
            },
            "discovered_hubs": ["https://hub.example.com/scholarships"],
            "discovered_hub_origins": {
                "https://hub.example.com/scholarships": "https://c.example.com/page2"
            },
        }
        marks, enqueues = [], []
        self._run_queue(seeds, summary, marks, enqueues)

        by_id = {sid: (ok, err) for sid, ok, err in marks}
        assert by_id["sa"] == (True, None)
        assert by_id["sb"] == (False, "HTTP 500")
        assert by_id["sc"] == (True, None)

    def test_missing_outcome_is_conservative_failure(self):
        seeds = [_seed("sx", "https://x.example.com")]
        marks, enqueues = [], []
        self._run_queue(seeds, {"seed_results": {}}, marks, enqueues)
        assert marks == [("sx", False, "no crawl outcome recorded for seed")]

    def test_hub_parent_is_actual_origin_page(self):
        seeds = [_seed("sa", "https://a.example.com"), _seed("sb", "https://b.example.com")]
        summary = {
            "seed_results": {
                "https://a.example.com": {"success": True, "error": ""},
                "https://b.example.com": {"success": True, "error": ""},
            },
            "discovered_hubs": ["https://hub.example.com/scholarships"],
            "discovered_hub_origins": {
                # Hub was found on B's child page, not the first seed.
                "https://hub.example.com/scholarships": "https://b.example.com/listings"
            },
        }
        marks, enqueues = [], []
        self._run_queue(seeds, summary, marks, enqueues)
        assert enqueues == [(["https://hub.example.com/scholarships"], "https://b.example.com/listings")]


# ---------------------------------------------------------------------------
# 5. Crawler-level per-seed outcomes and hub origins
# ---------------------------------------------------------------------------

class TestCrawlerSeedOutcomes:
    async def test_seed_root_fetch_determines_outcome(self):
        seeds = [
            "https://good.example.com",
            "https://bad.example.com",
            "https://partial.example.com",
        ]
        crawler = ScholarshipCrawler(seeds=seeds, max_depth=1, max_pages_per_domain=10)

        pages = {
            "https://good.example.com": '<html><body><a href="/x">x</a> scholarship award</body></html>',
            "https://partial.example.com": '<html><body><a href="/dead">dead</a> scholarship</body></html>',
        }

        async def _fake_fetch(client, url):
            if url == "https://bad.example.com":
                return "", False, "HTTP 500"
            if url.endswith("/dead"):
                return "", False, "HTTP 404"
            html = pages.get(url)
            return (html, True, "") if html else ("", False, "HTTP 404")

        crawler._fetch = _fake_fetch  # type: ignore[method-assign]
        await crawler.crawl()
        results = crawler.get_stats().seed_results

        assert results["https://good.example.com"] == (True, "")
        assert results["https://bad.example.com"] == (False, "HTTP 500")
        # Child 404 must not fail the seed whose root loaded fine.
        assert results["https://partial.example.com"] == (True, "")

    async def test_hub_origin_tracks_discovering_page(self):
        seed = "https://root.example.com"
        crawler = ScholarshipCrawler(seeds=[seed], max_depth=1, max_pages_per_domain=10)

        async def _fake_fetch(client, url):
            if url == seed:
                return ('<html><body><a href="https://root.example.com/scholarships/list">hub</a>'
                        ' scholarship award</body></html>'), True, ""
            return ('<html><body>scholarship grant funding</body></html>'), True, ""

        crawler._fetch = _fake_fetch  # type: ignore[method-assign]
        await crawler.crawl()
        stats = crawler.get_stats()
        hub = "https://root.example.com/scholarships/list"
        assert hub in stats.discovered_hubs
        assert stats.hub_origins[hub] == seed

    def test_invalid_seed_is_failure_not_silent_skip(self):
        crawler = ScholarshipCrawler(seeds=["not-a-url"], max_depth=1)
        # crawl() seeds the queue eagerly; invalid seeds fail immediately.
        import asyncio
        asyncio.run(crawler.crawl())
        res = crawler.get_stats().seed_results["not-a-url"]
        assert res[0] is False
        assert "invalid" in res[1].lower()
