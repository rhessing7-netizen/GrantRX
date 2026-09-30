"""Centralized polite-fetch policy (Catalog Batch C6).

Every outbound request in the catalog pipeline goes through ``FetchSession``:

  honest crawler identity -> robots.txt check -> per-host pacing ->
  bounded retry (status-aware, Retry-After) -> response + content hash

Design rules:

- One identity: ``EdFintiaBot`` — no rotating consumer User-Agents, no
  stealth. Configurable via env before the public crawler-info page exists.
- robots.txt (RFC 9309): 4xx -> allow; 2xx -> parsed rules for our agent
  with ``*`` fallback and Crawl-delay; 5xx/network -> "unavailable", which
  refuses the fetch for this run WITHOUT pretending the target is broken.
- Pacing is per host (a lock + timestamp), never a global sleep: different
  hosts proceed independently within the global concurrency bound.
- Retries only for transient failures (connection, timeout, 429, 5xx).
  404/410/robots denial/invalid URLs are terminal on the first response.
- 304 Not Modified is a successful check, not an error.
- Diagnostics are bounded: outcome + status code + exception class only —
  no headers, cookies, or page bodies.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import re
import time
import urllib.robotparser
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .utils.normalize import clean_text
from .utils.page_links import CHROME_TAGS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Crawler identity (C6.2)
# ---------------------------------------------------------------------------

CRAWLER_PRODUCT = "EdFintiaBot"
CRAWLER_VERSION = "1.0"
DEFAULT_INFO_URL = "https://edfintia.com/crawler"


def crawler_user_agent() -> str:
    """The single honest User-Agent for every outbound request.

    ``CRAWLER_USER_AGENT`` overrides the whole string; otherwise the product
    token + info URL are composed. ``CRAWLER_INFO_URL`` lets the ops team
    repoint the crawler-information link before the public page exists.
    """
    override = os.getenv("CRAWLER_USER_AGENT", "").strip()
    if override:
        return override
    info = os.getenv("CRAWLER_INFO_URL", DEFAULT_INFO_URL).strip() or DEFAULT_INFO_URL
    return f"{CRAWLER_PRODUCT}/{CRAWLER_VERSION} (+{info})"


def robots_agent_name() -> str:
    """The robots.txt user-agent token this crawler answers to.

    ``CRAWLER_ROBOTS_NAME`` overrides it; otherwise it is derived from the
    configured UA's product token so the two never drift apart.
    """
    override = os.getenv("CRAWLER_ROBOTS_NAME", "").strip()
    if override:
        return override.lower()
    return crawler_user_agent().split("/", 1)[0].split()[0].lower()


# ---------------------------------------------------------------------------
# Outcomes (C6.11 diagnostics)
# ---------------------------------------------------------------------------

OUTCOME_OK = "ok"
OUTCOME_NOT_MODIFIED = "not_modified"            # HTTP 304 — a successful check
OUTCOME_ROBOTS_DENIED = "robots_denied"          # robots.txt disallows us
OUTCOME_ROBOTS_UNAVAILABLE = "robots_unavailable"  # robots.txt itself 5xx/unreachable
OUTCOME_PERMANENT_HTTP = "permanent_http"        # definitive 4xx (404/410/…)
OUTCOME_ACCESS_DENIED = "access_denied"          # HTTP 403 — refusal, not removal (E2.5)
OUTCOME_TRANSIENT_HTTP = "transient_http"        # 429/5xx after retries exhausted
OUTCOME_TIMEOUT = "timeout"
OUTCOME_NETWORK_ERROR = "network_error"
OUTCOME_INVALID_URL = "invalid_url"

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
# Errors that must never be retried within a run (retries would be a storm):
_TERMINAL_STATUSES = {400, 401, 403, 404, 405, 410, 451}

# A link check/seed fetch that never got a definitive answer is INCONCLUSIVE —
# it is neither a success nor "the site is broken". HTTP 403 lands here: the
# crawler was denied access; nothing was learned about the resource itself.
INCONCLUSIVE_OUTCOMES = {
    OUTCOME_ROBOTS_DENIED,
    OUTCOME_ROBOTS_UNAVAILABLE,
    OUTCOME_TIMEOUT,
    OUTCOME_NETWORK_ERROR,
    OUTCOME_TRANSIENT_HTTP,
    OUTCOME_ACCESS_DENIED,
}

ROBOTS_OUTCOMES = {OUTCOME_ROBOTS_DENIED, OUTCOME_ROBOTS_UNAVAILABLE}


@dataclass
class FetchResult:
    """Bounded outcome of one logical fetch (retries collapsed)."""

    url: str
    outcome: str = OUTCOME_NETWORK_ERROR
    http_status: Optional[int] = None
    text: str = ""
    attempts: int = 0
    error: str = ""                       # bounded diagnostic only
    content_hash: Optional[str] = None
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    retry_after: Optional[float] = None   # Retry-After honored on the last hit
    final_url: Optional[str] = None       # resolved URL after redirects (C7)
    permanent_redirect: bool = False      # a 301/308 hop was followed (C7)

    @property
    def ok(self) -> bool:
        """A definitive response we may use — includes 304."""
        return self.outcome in (OUTCOME_OK, OUTCOME_NOT_MODIFIED)

    @property
    def is_robots_block(self) -> bool:
        return self.outcome in ROBOTS_OUTCOMES


# ---------------------------------------------------------------------------
# Content hashing (C6.7)
# ---------------------------------------------------------------------------

_HASH_STRIP_TAGS = ("script", "style", "noscript", "template", *CHROME_TAGS)


def content_hash(html: str) -> str:
    """Deterministic hash of the page's meaningful content.

    Hashing normalized visible text (not raw bytes) means transport-level
    differences — attribute ordering, whitespace, volatile markup — do not
    change the hash, while any real content change does.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all(_HASH_STRIP_TAGS):
        tag.decompose()
    text = clean_text(soup.get_text(" "))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Policy configuration
# ---------------------------------------------------------------------------


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


@dataclass(frozen=True)
class FetchPolicy:
    """Tunables for one run. Defaults are conservative for scheduled
    catalog crawling, not throughput."""

    timeout: float = 30.0
    min_interval: float = 3.0          # seconds between requests to one host
    per_host_concurrency: int = 2
    global_concurrency: int = 6
    max_retries: int = 2               # retries AFTER the first attempt
    backoff_base: float = 0.75         # exponential base, seconds
    retry_after_cap: float = 30.0      # max sleep honored from Retry-After
    robots_ttl: float = 3600.0         # seconds a robots decision is cached
    conditional_requests: bool = True  # send ETag/Last-Modified when known
    honor_crawl_delay: bool = True

    @classmethod
    def from_env(cls) -> "FetchPolicy":
        return cls(
            timeout=_env_float("CRAWLER_TIMEOUT", 30.0),
            min_interval=_env_float("CRAWLER_MIN_INTERVAL_SECONDS", 3.0),
            per_host_concurrency=max(1, _env_int("CRAWLER_MAX_HOST_CONCURRENCY", 2)),
            global_concurrency=max(1, _env_int("CRAWLER_MAX_CONCURRENCY", 6)),
            max_retries=_env_int("CRAWLER_MAX_RETRIES", 2),
            backoff_base=_env_float("CRAWLER_RETRY_BACKOFF_SECONDS", 0.75),
            retry_after_cap=_env_float("CRAWLER_RETRY_AFTER_CAP_SECONDS", 30.0),
            robots_ttl=_env_float("CRAWLER_ROBOTS_TTL_SECONDS", 3600.0),
        )


# ---------------------------------------------------------------------------
# robots.txt cache (C6.3)
# ---------------------------------------------------------------------------


@dataclass
class _RobotsEntry:
    parser: Optional[urllib.robotparser.RobotFileParser]
    fetched_at: float
    unavailable: bool = False
    crawl_delay: Optional[float] = None


class RobotsCache:
    """Per-origin robots.txt decisions, cached for the run."""

    def __init__(self, ttl: float, *, now: Callable[[], float] = time.monotonic):
        self._ttl = ttl
        self._now = now
        self._entries: Dict[str, _RobotsEntry] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    @staticmethod
    def _origin(url: str) -> str:
        p = urlparse(url)
        return f"{p.scheme.lower()}://{p.netloc.lower()}"

    async def allowed(
        self,
        url: str,
        *,
        fetch_robots: Callable[[str], Awaitable[Tuple[Optional[int], str]]],
        agent: str,
    ) -> Tuple[bool, Optional[float], str]:
        """Return (allowed, crawl_delay, reason).

        reason is one of OUTCOME_OK / OUTCOME_ROBOTS_DENIED /
        OUTCOME_ROBOTS_UNAVAILABLE — enough for the caller to build a
        FetchResult without re-parsing.
        """
        origin = self._origin(url)
        async with self._locks.setdefault(origin, asyncio.Lock()):
            entry = self._entries.get(origin)
            if entry is None or self._now() - entry.fetched_at > self._ttl:
                entry = await self._load(origin, fetch_robots, agent)
                self._entries[origin] = entry
        if entry.unavailable:
            return False, None, OUTCOME_ROBOTS_UNAVAILABLE
        if entry.parser is None:  # 4xx / empty / unparseable -> allow
            return True, entry.crawl_delay, OUTCOME_OK
        if not entry.parser.can_fetch(agent, url):
            return False, entry.crawl_delay, OUTCOME_ROBOTS_DENIED
        return True, entry.crawl_delay, OUTCOME_OK

    async def _load(
        self,
        origin: str,
        fetch_robots: Callable[[str], Awaitable[Tuple[Optional[int], str]]],
        agent: str,
    ) -> _RobotsEntry:
        status, body = await fetch_robots(f"{origin}/robots.txt")
        entry = _RobotsEntry(parser=None, fetched_at=self._now())
        if status is None or (status is not None and status >= 500):
            # RFC 9309: a 5xx (or unreachable) robots.txt is treated as a
            # complete disallow for this run — never silently fetch.
            entry.unavailable = True
            return entry
        if status >= 400:
            # 404/410/other 4xx: no robots.txt -> everything allowed.
            return entry
        parser = urllib.robotparser.RobotFileParser()
        try:
            parser.parse(body.splitlines())
        except Exception:  # noqa: BLE001 — unparseable robots behaves like none
            return entry
        entry.parser = parser
        try:
            delay = parser.crawl_delay(agent) or parser.crawl_delay("*")
        except Exception:  # noqa: BLE001
            delay = None
        if delay is not None:
            try:
                entry.crawl_delay = float(delay)
            except (TypeError, ValueError):
                entry.crawl_delay = None
        return entry


# ---------------------------------------------------------------------------
# FetchSession
# ---------------------------------------------------------------------------


@dataclass
class _HostState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    semaphore: Optional[asyncio.Semaphore] = None
    next_at: float = 0.0


class FetchSession:
    """One politeness boundary for all catalog HTTP.

    Shared across the fetcher, crawler, C5 detail fetches, and link checkers
    for the duration of a run so pacing/robots state is truly per-host.
    ``sleep``/``now`` are injectable so tests use a virtual clock.
    """

    def __init__(
        self,
        policy: Optional[FetchPolicy] = None,
        client: Optional[httpx.AsyncClient] = None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], float] = time.monotonic,
    ):
        self.policy = policy or FetchPolicy.from_env()
        self._client = client
        self._own_client = client is None
        self._sleep = sleep
        self._now = now
        self.robots = RobotsCache(self.policy.robots_ttl, now=now)
        self._hosts: Dict[str, _HostState] = {}
        self._global_sem = asyncio.Semaphore(self.policy.global_concurrency)
        self._validators: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
        self.content_hashes: Dict[str, str] = {}
        self.last_results: Dict[str, FetchResult] = {}
        self.outcome_counts: Counter = Counter()
        self.paced_waits: Dict[str, list] = {}

    async def _client_or_create(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.policy.timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": crawler_user_agent(),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._own_client:
            await self._client.aclose()
        self._client = None

    # -- host key + pacing --------------------------------------------------

    @staticmethod
    def _host_key(url: str) -> str:
        p = urlparse(url)
        return p.netloc.lower()

    def _host_state(self, host: str) -> _HostState:
        st = self._hosts.get(host)
        if st is None:
            st = _HostState(semaphore=asyncio.Semaphore(self.policy.per_host_concurrency))
            self._hosts[host] = st
        return st

    async def _pace(self, host: str, extra_interval: float = 0.0) -> None:
        """Reserve the next slot for this host. Serialized per host so two
        tasks can't claim the same slot; sleeps happen while holding the
        host lock only."""
        st = self._host_state(host)
        interval = max(self.policy.min_interval, extra_interval)
        async with st.lock:
            wait = st.next_at - self._now()
            if wait > 0:
                await self._sleep(wait)
            self.paced_waits.setdefault(host, []).append(max(wait, 0.0))
            st.next_at = max(self._now(), st.next_at) + interval

    # -- robots -------------------------------------------------------------

    async def _fetch_robots(self, robots_url: str) -> Tuple[Optional[int], str]:
        """Fetch robots.txt. The robots fetch itself is a request to the host
        and is paced — but it must not recursively check robots."""
        res = await self._raw_request(robots_url, "GET", {}, skip_robots=True)
        return res.http_status, res.text

    async def _robots_check(self, url: str) -> Tuple[bool, float, str]:
        allowed, delay, reason = await self.robots.allowed(
            url, fetch_robots=self._fetch_robots, agent=robots_agent_name(),
        )
        if not allowed:
            return False, 0.0, reason
        extra = 0.0
        if self.policy.honor_crawl_delay and delay is not None:
            extra = float(delay)
        return True, extra, reason

    # -- one raw attempt -----------------------------------------------------

    async def _raw_request(
        self,
        url: str,
        method: str,
        headers: Dict[str, str],
        *,
        timeout: Optional[float] = None,
        skip_robots: bool = False,
    ) -> FetchResult:
        """Single attempt: global+host concurrency, pacing, one request."""
        host = self._host_key(url)
        if not skip_robots:
            allowed, extra_interval, reason = await self._robots_check(url)
            if not allowed:
                return FetchResult(url=url, outcome=reason, error=reason)
        else:
            extra_interval = 0.0
        st = self._host_state(host)
        async with self._global_sem, st.semaphore:
            await self._pace(host, extra_interval)
            client = await self._client_or_create()
            # Identity is stamped per request so an injected/foreign client
            # can never emit a consumer UA on the wire.
            wire_headers = {
                "User-Agent": crawler_user_agent(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                **headers,
            }
            try:
                resp = await client.request(
                    method, url, headers=wire_headers,
                    timeout=timeout or self.policy.timeout,
                )
            except httpx.TimeoutException as exc:
                return FetchResult(url=url, outcome=OUTCOME_TIMEOUT,
                                   error=f"{type(exc).__name__}"[:200])
            except httpx.HTTPError as exc:
                return FetchResult(url=url, outcome=OUTCOME_NETWORK_ERROR,
                                   error=f"{type(exc).__name__}"[:200])
            except Exception as exc:  # noqa: BLE001 — e.g. invalid URL mid-flight
                return FetchResult(url=url, outcome=OUTCOME_INVALID_URL,
                                   error=f"{type(exc).__name__}"[:200])
        return self._from_response(url, resp)

    def _from_response(self, url: str, resp: httpx.Response) -> FetchResult:
        status = resp.status_code
        res = FetchResult(url=url, http_status=status)
        res.etag = resp.headers.get("ETag")
        res.last_modified = resp.headers.get("Last-Modified")
        ra = _parse_retry_after(resp.headers.get("Retry-After"))
        if ra is not None:
            res.retry_after = ra
        if resp.history:
            res.final_url = str(resp.url)
            res.permanent_redirect = any(
                r.status_code in (301, 308) for r in resp.history)
        if status == 304:
            res.outcome = OUTCOME_NOT_MODIFIED
            return res
        if status < 400:
            res.outcome = OUTCOME_OK
            res.text = resp.text
            return res
        # 403 is an access refusal — it proves the server spoke to us and
        # denied the request; it says nothing about whether the resource
        # exists. Never classify it as "the URL is gone".
        res.outcome = (OUTCOME_ACCESS_DENIED if status == 403
                       else OUTCOME_TRANSIENT_HTTP if status in _RETRYABLE_STATUSES
                       else OUTCOME_PERMANENT_HTTP)
        res.error = f"HTTP {status}"
        return res

    # -- public: GET with retry/validators/hash -------------------------------

    def prime_validators(self, url: str, etag: Optional[str],
                         last_modified: Optional[str]) -> None:
        """Seed durable validators (C7): a source registry row replays its
        stored ETag/Last-Modified so the next GET goes out conditional."""
        if not self.policy.conditional_requests:
            return
        if etag or last_modified:
            self._validators[url] = (etag, last_modified)

    async def get(self, url: str, *, timeout: Optional[float] = None,
                  headers: Optional[Dict[str, str]] = None,
                  conditional: bool = True) -> FetchResult:
        """Politely GET a URL: robots -> pacing -> bounded retry.

        ``conditional=False`` forces an unconditional GET — used when a 304
        left a source with extracted content still pending (C7)."""
        if not _valid_http_url(url):
            return self._record(FetchResult(url=url, outcome=OUTCOME_INVALID_URL,
                                            error="invalid URL"))
        req_headers = dict(headers or {})
        if self.policy.conditional_requests and conditional:
            etag, lastmod = self._validators.get(url, (None, None))
            if etag:
                req_headers.setdefault("If-None-Match", etag)
            if lastmod:
                req_headers.setdefault("If-Modified-Since", lastmod)

        attempts = 0
        result = FetchResult(url=url)
        while True:
            attempts += 1
            result = await self._raw_request(url, "GET", req_headers, timeout=timeout)
            result.attempts = attempts
            if not self._retryable(result) or attempts > self.policy.max_retries:
                break
            await self._sleep(self._retry_delay(result, attempts))

        if result.outcome == OUTCOME_OK:
            result.content_hash = content_hash(result.text)
            self.content_hashes[url] = result.content_hash
            if result.etag or result.last_modified:
                self._validators[url] = (result.etag, result.last_modified)
        return self._record(result)

    async def check(self, url: str, *, timeout: Optional[float] = None) -> FetchResult:
        """HEAD-then-GET existence check for link verification.

        Same robots/pacing/retry policy as ``get``. The caller decides what
        the outcome means; a 304 or <400 is ok, a real 4xx is definitive,
        everything else is inconclusive."""
        if not _valid_http_url(url):
            return self._record(FetchResult(url=url, outcome=OUTCOME_INVALID_URL,
                                            error="invalid URL"))
        attempts = 0
        result = FetchResult(url=url)
        method = "HEAD"
        while True:
            attempts += 1
            result = await self._raw_request(url, method, {}, timeout=timeout)
            result.attempts = attempts
            if method == "HEAD" and result.http_status == 405:
                method = "GET"
                continue  # server can't HEAD — GET counts as the retry of this check
            if not self._retryable(result) or attempts > self.policy.max_retries:
                break
            await self._sleep(self._retry_delay(result, attempts))
        return self._record(result)

    @asynccontextmanager
    async def acquire(self, url: str) -> "AsyncIterator[Optional[FetchResult]]":
        """Hold global+host slots through a non-httpx fetch (Playwright).

        The robots check happens before the caller starts any work; the
        per-host/global slots stay held for the whole navigation so two
        browser renders to one host never overlap. Yields None when the
        caller may fetch, or a FetchResult describing the denial/invalid URL.
        """
        if not _valid_http_url(url):
            yield self._record(FetchResult(url=url, outcome=OUTCOME_INVALID_URL,
                                           error="invalid URL"))
            return
        allowed, extra_interval, reason = await self._robots_check(url)
        if not allowed:
            yield self._record(FetchResult(url=url, outcome=reason, error=reason))
            return
        host = self._host_key(url)
        st = self._host_state(host)
        async with self._global_sem, st.semaphore:
            await self._pace(host, extra_interval)
            yield None  # slots held; caller fetches now

    # -- retry helpers -------------------------------------------------------

    def _retryable(self, res: FetchResult) -> bool:
        if res.outcome in (OUTCOME_TIMEOUT, OUTCOME_NETWORK_ERROR):
            return True
        return bool(res.http_status and res.http_status in _RETRYABLE_STATUSES)

    def _retry_delay(self, res: FetchResult, attempt: int) -> float:
        if res.retry_after is not None:
            return min(res.retry_after, self.policy.retry_after_cap)
        backoff = self.policy.backoff_base * (2 ** (attempt - 1))
        return min(backoff + random.uniform(0, backoff), self.policy.retry_after_cap)

    def _record(self, res: FetchResult) -> FetchResult:
        self.outcome_counts[res.outcome] += 1
        self.last_results[res.url] = res
        return res

    def outcomes_summary(self) -> dict:
        return dict(self.outcome_counts)


def _valid_http_url(url: str) -> bool:
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    value = value.strip()
    if re.fullmatch(r"\d+", value):
        return float(value)
    try:
        from datetime import datetime, timezone
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(value)
        now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
        return max(0.0, (dt - now).total_seconds())
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Shared session for the run
# ---------------------------------------------------------------------------

_default_session: Optional[FetchSession] = None
_default_loop: Optional[asyncio.AbstractEventLoop] = None


def default_session() -> FetchSession:
    """The run-shared FetchSession.

    Bound to the current event loop: ``asyncio.run`` creates a new loop per
    invocation, so a session must not leak across loops (its httpx pool and
    asyncio primitives are loop-bound).
    """
    global _default_session, _default_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _default_session is None or _default_loop is not loop:
        _default_session = FetchSession()
        _default_loop = loop
    return _default_session


async def aclose_default_session() -> None:
    global _default_session
    if _default_session is not None:
        await _default_session.aclose()
