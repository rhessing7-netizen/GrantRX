"""C6 polite & compliant fetching tests — all traffic is local MockTransport.

No public websites are contacted: httpx.MockTransport serves every response,
and pacing/retry sleeps run on a virtual clock where determinism matters.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Tuple
from unittest.mock import patch

import httpx
import pytest

from scrapers import crawler as crawler_mod
from scrapers import fetcher, runner
from scrapers.fetch_policy import (
    OUTCOME_NOT_MODIFIED,
    OUTCOME_PERMANENT_HTTP,
    OUTCOME_ROBOTS_DENIED,
    OUTCOME_ROBOTS_UNAVAILABLE,
    OUTCOME_TIMEOUT,
    FetchPolicy,
    FetchResult,
    FetchSession,
    content_hash,
    crawler_user_agent,
    robots_agent_name,
)


def _run(coro):
    return asyncio.run(coro)


class Clock:
    """Virtual clock: `now` only advances when the session sleeps."""

    def __init__(self):
        self.t = 0.0
        self.sleeps: List[float] = []

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


class Server:
    """Scriptable MockTransport handler with request recording."""

    def __init__(self):
        self.responses: Dict[Tuple[str, str], object] = {}
        self.requests: List[httpx.Request] = []
        self.headers_seen: List[dict] = []
        self.inflight = 0
        self.max_inflight = 0
        self.delay = 0.0

    def add(self, method: str, url: str, response) -> None:
        self.responses[(method, url)] = response

    def add_page(self, url: str, body: str = "<html><body>ok</body></html>",
                 headers: Optional[dict] = None, status: int = 200) -> None:
        self.add("GET", url, httpx.Response(status, text=body, headers=headers or {}))

    def add_robots(self, host_url: str, body: Optional[str], status: int = 200) -> None:
        if body is None:
            self.add("GET", f"{host_url}/robots.txt", httpx.Response(404, text="not found"))
        else:
            self.add("GET", f"{host_url}/robots.txt", httpx.Response(status, text=body))

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.headers_seen.append(dict(request.headers))
        key = (request.method, str(request.url))
        resp = self.responses.get(key)
        if isinstance(resp, Exception):
            raise resp
        if resp is None:
            return httpx.Response(404, text="not found")
        return resp


def make_session(server: Server, *, clock: Optional[Clock] = None, **policy_kw) -> FetchSession:
    kw = {"min_interval": 0.0, "max_retries": 2, "backoff_base": 0.5, "retry_after_cap": 5.0}
    kw.update(policy_kw)
    policy = FetchPolicy(**kw)
    client = httpx.AsyncClient(transport=httpx.MockTransport(server.handler),
                               follow_redirects=True)
    if clock is not None:
        return FetchSession(policy=policy, client=client, sleep=clock.sleep, now=clock.now)
    return FetchSession(policy=policy, client=client)


ALLOW_ALL = "User-agent: *\nDisallow:\n"
DENY_PRIVATE = "User-agent: *\nDisallow: /private/\n"
DENY_BOT = "User-agent: *\nDisallow:\n\nUser-agent: EdFintiaBot\nDisallow: /\n"
CRAWL_DELAY = "User-agent: *\nDisallow:\nCrawl-delay: 2\n"

BASE = "https://host-a.example.org"


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

class TestIdentity:
    def test_honest_ua_format(self):
        ua = crawler_user_agent()
        assert ua.startswith("EdFintiaBot/") and "(+" in ua and ua.endswith(")")
        assert "Mozilla" not in ua

    def test_robots_token_matches_ua(self):
        assert robots_agent_name() == "edfintiabot"

    def test_ua_sent_on_wire(self):
        s = Server()
        s.add_robots(BASE, ALLOW_ALL)
        s.add_page(f"{BASE}/x")
        session = make_session(s)
        _run(session.get(f"{BASE}/x"))
        page_req = [r for r in s.requests if r.url.path == "/x"][0]
        assert "EdFintiaBot" in page_req.headers["user-agent"]
        assert "Mozilla" not in page_req.headers["user-agent"]


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------

class TestRobots:
    def _session_for(self, body, status=200):
        s = Server()
        s.add_robots(BASE, body, status)
        s.add_page(f"{BASE}/open")
        s.add_page(f"{BASE}/private/thing")
        clock = Clock()
        return s, make_session(s, clock=clock)

    def test_allow(self):
        s, session = self._session_for(ALLOW_ALL)
        res = _run(session.get(f"{BASE}/open"))
        assert res.outcome == "ok" and res.text

    def test_deny_wildcard(self):
        s, session = self._session_for(DENY_PRIVATE)
        denied = _run(session.get(f"{BASE}/private/thing"))
        assert denied.outcome == OUTCOME_ROBOTS_DENIED
        allowed = _run(session.get(f"{BASE}/open"))
        assert allowed.outcome == "ok"
        # The denied page was never requested — only robots.txt + the open page.
        assert not any(r.url.path == "/private/thing" for r in s.requests)

    def test_crawler_specific_rule(self):
        s, session = self._session_for(DENY_BOT)
        res = _run(session.get(f"{BASE}/open"))
        assert res.outcome == OUTCOME_ROBOTS_DENIED

    def test_missing_robots_allows(self):
        s, session = self._session_for(None)  # 404
        res = _run(session.get(f"{BASE}/open"))
        assert res.outcome == "ok"

    def test_robots_5xx_is_unavailable_not_denied(self):
        s, session = self._session_for("server error", status=500)
        res = _run(session.get(f"{BASE}/open"))
        assert res.outcome == OUTCOME_ROBOTS_UNAVAILABLE
        # And the page itself was never fetched.
        assert not any(r.url.path == "/open" for r in s.requests)

    def test_robots_cached_per_host(self):
        s, session = self._session_for(ALLOW_ALL)
        _run(session.get(f"{BASE}/open"))
        _run(session.get(f"{BASE}/open"))
        robots_calls = [r for r in s.requests if r.url.path == "/robots.txt"]
        assert len(robots_calls) == 1

    def test_crawl_delay_paces_requests(self):
        s, session = self._session_for(CRAWL_DELAY)
        clock = session._sleep.__self__ if hasattr(session._sleep, "__self__") else None
        _run(session.get(f"{BASE}/open"))
        _run(session.get(f"{BASE}/open"))
        waits = session.paced_waits["host-a.example.org"]
        # Last wait must reflect the 2s crawl-delay, not the 0 min_interval.
        assert waits[-1] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Pacing / concurrency
# ---------------------------------------------------------------------------

class TestPacing:
    def test_same_host_spacing(self):
        s = Server()
        s.add_robots(BASE, ALLOW_ALL)
        s.add_page(f"{BASE}/a")
        s.add_page(f"{BASE}/b")
        s.add_page(f"{BASE}/c")
        clock = Clock()
        session = make_session(s, clock=clock, min_interval=5.0)

        async def go():
            for p in ("/a", "/b", "/c"):
                await session.get(BASE + p)
        _run(go())
        waits = session.paced_waits["host-a.example.org"]
        # robots fetch, then 3 pages — every request after the first waits ≥5s.
        assert waits[0] == 0.0
        assert all(w == pytest.approx(5.0) for w in waits[2:])

    def test_different_hosts_independent(self):
        s = Server()
        s.add_robots(BASE, ALLOW_ALL)
        s.add_robots("https://host-b.example.org", ALLOW_ALL)
        s.add_page(f"{BASE}/a")
        s.add_page("https://host-b.example.org/a")
        clock = Clock()
        session = make_session(s, clock=clock, min_interval=5.0)
        _run(session.get(f"{BASE}/a"))
        _run(session.get("https://host-b.example.org/a"))
        # Host B's first request does not inherit host A's pacing debt.
        assert session.paced_waits["host-b.example.org"][0] == 0.0

    def test_per_host_concurrency_cap(self):
        s = Server()
        s.add_robots(BASE, ALLOW_ALL)
        inflight = {"n": 0, "max": 0}

        async def handler(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text=ALLOW_ALL)
            inflight["n"] += 1
            inflight["max"] = max(inflight["max"], inflight["n"])
            await asyncio.sleep(0.02)
            inflight["n"] -= 1
            return httpx.Response(200, text="ok")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session = FetchSession(policy=FetchPolicy(min_interval=0, per_host_concurrency=1),
                               client=client)
        urls = [f"{BASE}/p{i}" for i in range(4)]

        async def go():
            await asyncio.gather(*(session.get(u) for u in urls))
        _run(go())
        assert inflight["max"] == 1

    def test_global_concurrency_cap(self):
        inflight = {"n": 0, "max": 0}

        async def handler(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text=ALLOW_ALL)
            inflight["n"] += 1
            inflight["max"] = max(inflight["max"], inflight["n"])
            await asyncio.sleep(0.02)
            inflight["n"] -= 1
            return httpx.Response(200, text="ok")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session = FetchSession(
            policy=FetchPolicy(min_interval=0, global_concurrency=2, per_host_concurrency=10),
            client=client)
        urls = [f"https://h{i}.example.org/p" for i in range(5)]

        async def go():
            await asyncio.gather(*(session.get(u) for u in urls))
        _run(go())
        assert inflight["max"] == 2


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------

class TestRetries:
    def _sleeper(self, session):
        return session._sleep

    def test_429_retry_after_honored(self):
        s = Server()
        s.add_robots(BASE, ALLOW_ALL)
        clock = Clock()
        session = make_session(s, clock=clock)
        calls = {"n": 0}

        def handler(request):
            if request.url.path == "/p":
                calls["n"] += 1
                if calls["n"] == 1:
                    return httpx.Response(429, headers={"Retry-After": "2"})
                return httpx.Response(200, text="ok")
            return s.handler(request)
        session._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session._own_client = False
        res = _run(session.get(f"{BASE}/p"))
        assert res.outcome == "ok" and res.attempts == 2
        assert 2.0 in clock.sleeps  # honored Retry-After, not just backoff

    def test_500_recovers(self):
        s = Server()
        s.add_robots(BASE, ALLOW_ALL)
        calls = {"n": 0}

        def handler(request):
            if request.url.path == "/p":
                calls["n"] += 1
                if calls["n"] == 1:
                    return httpx.Response(500, text="boom")
                return httpx.Response(200, text="ok")
            return s.handler(request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session = FetchSession(policy=FetchPolicy(min_interval=0, max_retries=2), client=client)
        res = _run(session.get(f"{BASE}/p"))
        assert res.outcome == "ok" and res.attempts == 2

    def test_404_never_retried(self):
        s = Server()
        s.add_robots(BASE, ALLOW_ALL)
        clock = Clock()
        session = make_session(s, clock=clock)
        res = _run(session.get(f"{BASE}/missing"))
        assert res.outcome == OUTCOME_PERMANENT_HTTP and res.attempts == 1

    def test_timeout_retried_then_gives_up(self):
        s = Server()
        s.add_robots(BASE, ALLOW_ALL)

        def handler(request):
            if request.url.path == "/slow":
                raise httpx.ReadTimeout("timed out", request=request)
            return s.handler(request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session = FetchSession(policy=FetchPolicy(min_interval=0, max_retries=2), client=client)
        res = _run(session.get(f"{BASE}/slow"))
        assert res.outcome == OUTCOME_TIMEOUT and res.attempts == 3  # 1 + 2 retries

    def test_retries_still_paced(self):
        s = Server()
        s.add_robots(BASE, ALLOW_ALL)
        calls = {"n": 0}

        def handler(request):
            if request.url.path == "/flaky" and calls["n"] < 2:
                calls["n"] += 1
                return httpx.Response(503, text="x")
            return s.handler(request)

        s.add_page(f"{BASE}/flaky")
        clock = Clock()
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session = FetchSession(policy=FetchPolicy(min_interval=3.0, max_retries=2,
                                                  backoff_base=0.0, retry_after_cap=0.0),
                               client=client, sleep=clock.sleep, now=clock.now)
        res = _run(session.get(f"{BASE}/flaky"))
        assert res.attempts == 3
        # Every attempt passed through the host gate (robots fetch + 3 tries).
        assert len(session.paced_waits["host-a.example.org"]) == 4


# ---------------------------------------------------------------------------
# Conditional requests / content hash
# ---------------------------------------------------------------------------

class TestCachingAndHashing:
    def test_etag_conditional_and_304(self):
        s = Server()
        s.add_robots(BASE, ALLOW_ALL)
        s.add("GET", f"{BASE}/p", httpx.Response(200, text="v1", headers={"ETag": '"abc"'}))
        session = make_session(s)
        _run(session.get(f"{BASE}/p"))

        def handler(request):
            if request.url.path == "/p":
                assert request.headers.get("If-None-Match") == '"abc"'
                return httpx.Response(304)
            return s.handler(request)

        session._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session._own_client = False
        res = _run(session.get(f"{BASE}/p"))
        assert res.outcome == OUTCOME_NOT_MODIFIED and res.ok and not res.text

    def test_last_modified_conditional(self):
        s = Server()
        s.add_robots(BASE, ALLOW_ALL)
        s.add("GET", f"{BASE}/p", httpx.Response(
            200, text="v1", headers={"Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT"}))
        seen = {}

        def handler(request):
            if request.url.path == "/p":
                seen["ims"] = request.headers.get("If-Modified-Since")
                return httpx.Response(304)
            return s.handler(request)

        session = make_session(s)
        _run(session.get(f"{BASE}/p"))
        session._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session._own_client = False
        _run(session.get(f"{BASE}/p"))
        assert seen["ims"] == "Wed, 01 Jan 2025 00:00:00 GMT"

    def test_content_hash_stable_across_transport_noise(self):
        a = "<html><body><p>Alpha   Scholarship  $5,000</p></body></html>"
        b = "<html>\n  <body>\n    <p>Alpha Scholarship $5,000</p>\n  </body>\n</html>"
        c = "<html><body><p>Alpha Scholarship $9,000</p></body></html>"
        assert content_hash(a) == content_hash(b)
        assert content_hash(a) != content_hash(c)

    def test_hash_recorded_per_url(self):
        s = Server()
        s.add_robots(BASE, ALLOW_ALL)
        s.add_page(f"{BASE}/p", "<html><body>hello grant</body></html>")
        session = make_session(s)
        res = _run(session.get(f"{BASE}/p"))
        assert res.content_hash == session.content_hashes[f"{BASE}/p"]


# ---------------------------------------------------------------------------
# Higher-level integration: fetcher, crawler outcomes, seeds, C5 details
# ---------------------------------------------------------------------------

class TestFetcherIntegration:
    def test_fetch_html_returns_empty_on_robots_denial(self):
        s = Server()
        s.add_robots(BASE, DENY_BOT)
        session = make_session(s)
        html = _run(fetcher.fetch_html(f"{BASE}/open", session=session))
        assert html == ""
        assert not any(r.url.path == "/open" for r in s.requests)

    def test_no_stealth_in_playwright_config(self):
        import inspect

        src = inspect.getsource(fetcher)
        assert "AutomationControlled" not in src
        assert "webdriver" not in src

    def test_playwright_refused_before_launch_on_denial(self):
        s = Server()
        s.add_robots(BASE, DENY_BOT)
        session = make_session(s)
        # If policy is enforced before the browser launch, this returns None
        # without ever importing playwright.
        rendered = _run(fetcher._fetch_with_playwright(f"{BASE}/open", session=session))
        assert rendered is None


class TestCrawlerOutcomeMapping:
    def test_robots_denial_maps_to_seed_outcome(self):
        crawler = crawler_mod.ScholarshipCrawler(seeds=[f"{BASE}/"], max_depth=0)

        class FakeSession:
            async def get(self, url, **kw):
                return FetchResult(url=url, outcome=OUTCOME_ROBOTS_DENIED,
                                   error=OUTCOME_ROBOTS_DENIED)

        _run(crawler._fetch(FakeSession(), f"{BASE}/"))
        # Through crawl() the root seed must record the robots outcome, not a
        # generic network failure.
        crawler2 = crawler_mod.ScholarshipCrawler(seeds=[f"{BASE}/"], max_depth=0)

        async def fake_fetch(client, url):
            return "", False, OUTCOME_ROBOTS_DENIED

        crawler2._fetch = fake_fetch  # type: ignore[method-assign]
        _run(crawler2.crawl())
        assert crawler2.get_stats().seed_results[f"{BASE}/"] == (False, OUTCOME_ROBOTS_DENIED)

    def test_queue_driver_uses_robots_path_not_failure(self):
        seeds = [{"id": "s1", "url": f"{BASE}/", "category": "t", "priority": 1,
                  "status": "queued", "last_crawled_at": None, "error_count": 0}]
        marks, robots_marks, enq = [], [], []

        async def _fake_crawl(seed_urls, **kw):
            return {"seed_results": {f"{BASE}/": {"success": False, "error": "robots_denied"}},
                    "discovered_hubs": [], "discovered_hub_origins": {}}

        with patch.object(runner, "run_crawl_pipeline", _fake_crawl), \
             patch("scrapers.seed_queue.get_next_seed_batch", return_value=seeds), \
             patch("scrapers.seed_queue.mark_seed_crawled",
                   lambda db, sid, success, error=None: marks.append((sid, success, error))), \
             patch("scrapers.seed_queue.mark_seed_robots_denied",
                   lambda db, sid, detail="robots_denied": robots_marks.append((sid, detail))), \
             patch("scrapers.seed_queue.enqueue_discovered_seeds",
                   lambda db, urls, parent_url, detected_category: enq.append(urls) or 0), \
             patch("app.database.SessionLocal") as mock_sl:
            from unittest.mock import MagicMock
            mock_sl.return_value = MagicMock()
            _run(runner.run_dynamic_queue_pipeline(queue_limit=5))

        assert robots_marks == [("s1", "robots_denied")]
        assert marks == []  # failure accounting never touched


class TestRepairUnchecked:
    def test_inconclusive_check_does_not_archive(self):
        import scripts.repair_urls as ru

        s_row = type("Row", (), {})()
        s_row.portal_url = f"{BASE}/apply"
        s_row.title = "T"
        s_row.provider = "P"
        s_row.source_url = None
        s_row.last_checked_at = None

        async def _fake(url):
            return ru.UNCHECKABLE

        with patch.object(ru, "_check_url", _fake):
            action = _run(ru.repair_one(s_row, {}))
        assert action == "unchecked"
        assert getattr(s_row, "lifecycle_status", None) != "archived"


class TestDetailFetchDenial:
    def test_c5_child_survives_robots_denied_detail(self):
        """Listing allowed + detail robots-denied -> child kept, detail_failed."""
        from scrapers.extraction import ExtractionLimits, extract_page
        from tests import c5_fixtures as fx

        s = Server()
        s.add_robots(BASE, DENY_BOT)
        session = make_session(s)

        async def denied_detail(u):
            return await fetcher.fetch_html(u, session=session) or None

        detail_items = [d for d in fx.listing_items() if d["title"].startswith("Alpha")]
        with patch("scrapers.llm_parser.extract_opportunities_with_llm",
                   fx.fake_llm_factory({fx.LISTING_URL: detail_items})):
            page = _run(extract_page(
                # Single-card listing is classified single; force listing
                # semantics by using the multi-item fixture with one scripted child.
                fx.listing_html(), fx.LISTING_URL,
                limits=ExtractionLimits(), fetch_detail=denied_detail))

        alpha = next((e for e in page.extracts if e.title.startswith("Alpha")), None)
        assert alpha is not None  # child survived despite denied detail fetch
        assert page.detail_attempted >= 1 and page.detail_failed >= 1
        assert alpha.award_amount == 5000  # listing-page facts preserved


class TestPortalCheckDecisive:
    def test_inconclusive_portal_check_keeps_record_unverified(self):
        async def _inconclusive(url, **kw):
            return FetchResult(url=url, outcome=OUTCOME_ROBOTS_DENIED,
                               error=OUTCOME_ROBOTS_DENIED)

        with patch.object(runner, "_check_url_result", _inconclusive):
            url, ok, decisive = _run(runner._verify_portal_url(
                "https://x.example.org/apply", "https://x.example.org/"))
        assert ok is True and decisive is False

    def test_real_404_is_decisive_dead(self):
        async def _dead(url, **kw):
            return FetchResult(url=url, outcome=OUTCOME_PERMANENT_HTTP, http_status=404)

        with patch.object(runner, "_check_url_result", _dead):
            url, ok, decisive = _run(runner._verify_portal_url(
                "https://x.example.org/apply", "https://x.example.org/"))
        assert ok is False and decisive is True
