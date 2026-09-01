"""Focused web crawler for discovering new healthcare scholarship sources.

Crawls seed URLs (university financial aid pages, foundation directories, etc.)
up to a configurable depth, filters links by scholarship-related keywords,
verifies page content for clinical/education relevance, and returns candidate
URLs + raw HTML for the LLM extraction pipeline.

Usage:
    from scrapers.crawler import ScholarshipCrawler

    crawler = ScholarshipCrawler(
        seeds=["https://www.aacp.org/student-awards"],
        max_depth=2,
        max_pages_per_domain=15,
    )
    candidates = await crawler.crawl()
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from .metro_filters import detect_all_metros, metro_name

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 20.0
DEFAULT_MAX_DEPTH = 2
DEFAULT_MAX_PAGES_PER_DOMAIN = 15
MIN_RELEVANCE_SCORE = 2  # minimum keyword hits for a page to be considered relevant

# Path keywords — links containing these are worth following
PATH_KEYWORDS = [
    "scholarship",
    "grant",
    "fellowship",
    "financial-aid",
    "financial_aid",
    "award",
    "tuition-assistance",
    "tuition_assistance",
    "loan-repayment",
    "loan_repayment",
    "apply",
    "funding",
]

# Content keywords — pages must contain enough of these to be relevant
# Synchronized with the expanded healthcare taxonomy
CONTENT_KEYWORDS = [
    # Core scholarship terms
    "eligibility",
    "deadline",
    "amount",
    "gpa",
    "apply",
    "scholarship",
    "award",
    "recipient",
    "applicant",
    "enrollment",
    "tuition",
    # Pharmacy
    "pharmacy",
    "pharmd",
    "pharmaceutical",
    "pharmacology",
    # Medicine
    "medicine",
    "medical",
    "physician",
    "osteopathic",
    "podiatry",
    "chiropractic",
    "naturopathic",
    # Nursing
    "nursing",
    "nurse",
    "midwifery",
    # Dentistry
    "dentistry",
    "dental",
    # Allied health
    "physician assistant",
    "physical therapy",
    "occupational therapy",
    "speech-language",
    "speech language",
    "audiology",
    "respiratory therapy",
    "athletic training",
    "exercise science",
    "kinesiology",
    # Public health & administration
    "public health",
    "health administration",
    "health informatics",
    # Lab & imaging
    "medical laboratory",
    "radiologic",
    "sonography",
    "ultrasound",
    # Mental health
    "clinical psychology",
    "mental health counseling",
    "social work",
    # Nutrition
    "dietetics",
    "nutrition",
    # Emergency
    "emergency medical",
    "paramedic",
    "emt",
    # Veterinary
    "veterinary",
    # General
    "health",
    "clinical",
    "student",
    "graduate",
    "undergraduate",
    "fellowship",
    "grant",
    "loan repayment",
]

# ---------------------------------------------------------------------------
# Regional filters — boost candidates with Ohio/Pennsylvania residency signals
# ---------------------------------------------------------------------------

REGIONAL_FILTERS = {
    # Geographic signals
    "target_states": ["ohio", "pennsylvania", "oh", "pa"],
    "target_counties": [
        "cuyahoga", "summit", "wayne", "stark", "franklin", "hamilton",
        "allegheny", "westmoreland", "erie", "philadelphia", "bucks", "montgomery",
    ],
    # High-intent local terms
    "local_context_terms": [
        "appalachian", "rural health", "medically underserved",
        "health professional shortage area", "hpsa", "northeast ohio", "western pennsylvania",
    ],
}

# State name -> 2-letter code mapping for residency extraction
_STATE_NAME_TO_CODE = {
    "ohio": "OH",
    "pennsylvania": "PA",
}

# Boost applied per regional keyword hit
REGIONAL_BOOST_PER_HIT = 3

# Boost applied when a Top-20 metro area is detected in page text
METRO_BOOST = 4

# File extensions to reject
REJECTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".zip", ".tar", ".gz", ".rar",
    ".mp4", ".avi", ".mov", ".wmv", ".mp3", ".wav",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
}

# Negative path patterns — drop non-grant pages before scoring
NEGATIVE_PATH_PATTERNS = [
    "/about-us/",
    "/board-of-trustees",
    "/staff-directory",
    "/press-release",
    "/news/",
    "/annual-report",
    "/about/",
    "/contact",
    "/privacy",
    "/terms",
    "/accessibility",
    "/sitemap",
]

# External mega-aggregators to never crawl (avoid drifting into generic scholarship databases)
BLOCKED_DOMAINS = {
    "fastweb.com",
    "scholarships.com",
    "studentaid.gov",
    "collegeboard.org",
    "bigfuture.collegeboard.org",
    "niche.com",
    "cappex.com",
    "scholarshipportal.com",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def _random_ua() -> str:
    return random.choice(USER_AGENTS)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class CrawlCandidate:
    """A discovered page that passed heuristic verification."""

    url: str
    title: str
    html: str
    text: str
    relevance_score: int
    matched_keywords: List[str] = field(default_factory=list)
    seed_url: str = ""
    depth: int = 0
    state_restriction: Optional[str] = None
    regional_keywords: List[str] = field(default_factory=list)


@dataclass
class CrawlStats:
    """Summary statistics from a crawl run."""

    pages_crawled: int = 0
    links_followed: int = 0
    links_rejected: int = 0
    candidates_found: int = 0
    errors: int = 0
    domains_visited: Set[str] = field(default_factory=set)

    def summary(self) -> dict:
        return {
            "pages_crawled": self.pages_crawled,
            "links_followed": self.links_followed,
            "links_rejected": self.links_rejected,
            "candidates_found": self.candidates_found,
            "errors": self.errors,
            "domains_visited": list(self.domains_visited),
        }


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------


class ScholarshipCrawler:
    """Focused web crawler that discovers scholarship pages.

    Args:
        seeds: List of root URLs to start crawling from.
        max_depth: Maximum crawl depth from each seed (default 2).
        max_pages_per_domain: Hard cap on pages fetched per domain (default 15).
        timeout: Per-request timeout in seconds.
        min_relevance: Minimum content keyword score for a page to be a candidate.
    """

    def __init__(
        self,
        seeds: List[str],
        *,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_pages_per_domain: int = DEFAULT_MAX_PAGES_PER_DOMAIN,
        timeout: float = DEFAULT_TIMEOUT,
        min_relevance: int = MIN_RELEVANCE_SCORE,
    ):
        self.seeds = seeds
        self.max_depth = max_depth
        self.max_pages_per_domain = max_pages_per_domain
        self.timeout = timeout
        self.min_relevance = min_relevance

        # State
        self._visited: Set[str] = set()
        self._domain_counts: Dict[str, int] = {}
        self._stats = CrawlStats()
        self._queue: List[Tuple[str, int, str]] = []  # (url, depth, seed_url)

    async def crawl(self) -> List[CrawlCandidate]:
        """Execute the crawl and return verified candidate pages."""
        # Seed the queue
        for seed in self.seeds:
            normalized = self._normalize_url(seed)
            if normalized:
                self._queue.append((normalized, 0, normalized))

        candidates: List[CrawlCandidate] = []

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": _random_ua()},
        ) as client:
            while self._queue:
                url, depth, seed_url = self._queue.pop(0)

                # Skip already visited
                if url in self._visited:
                    continue
                self._visited.add(url)

                # Check domain page cap
                domain = self._get_domain(url)
                if self._domain_counts.get(domain, 0) >= self.max_pages_per_domain:
                    logger.debug("Domain cap reached for %s — skipping %s", domain, url)
                    continue

                # Fetch the page
                html, ok = await self._fetch(client, url)
                if not ok or not html:
                    self._stats.errors += 1
                    continue

                self._stats.pages_crawled += 1
                self._domain_counts[domain] = self._domain_counts.get(domain, 0) + 1
                self._stats.domains_visited.add(domain)

                # Parse and evaluate content
                text, title, links = self._parse_page(html, url)
                base_score, matched, regional_score, regional_kws, state_restriction = self._score_content(text)
                total_score = base_score + regional_score

                logger.debug(
                    "Crawled [depth=%d] %s — base=%d, regional=%d, total=%d, links=%d, state=%s",
                    depth, url, base_score, regional_score, total_score, len(links), state_restriction,
                )

                # Skip negative path patterns even if content scored well
                url_path = urlparse(url).path.lower()
                if any(pattern in url_path for pattern in NEGATIVE_PATH_PATTERNS):
                    logger.debug("Skipping negative path: %s", url)
                elif total_score >= self.min_relevance:
                    candidate = CrawlCandidate(
                        url=url,
                        title=title,
                        html=html,
                        text=text,
                        relevance_score=total_score,
                        matched_keywords=matched,
                        seed_url=seed_url,
                        depth=depth,
                        state_restriction=state_restriction,
                        regional_keywords=regional_kws,
                    )
                    candidates.append(candidate)
                    self._stats.candidates_found += 1
                    regional_str = f", regional={regional_score}" if regional_score else ""
                    state_str = f", state={state_restriction}" if state_restriction else ""
                    logger.info(
                        "Candidate found: %s (score=%d%s%s, keywords=%s)",
                        url, total_score, regional_str, state_str, matched[:5],
                    )

                # Enqueue child links if we haven't reached max depth
                if depth < self.max_depth:
                    for link in links:
                        if link in self._visited:
                            continue
                        if self._should_follow(link, url):
                            self._queue.append((link, depth + 1, seed_url))
                            self._stats.links_followed += 1
                        else:
                            self._stats.links_rejected += 1

        logger.info("Crawl complete: %s", self._stats.summary())
        return candidates

    def get_stats(self) -> CrawlStats:
        return self._stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> Tuple[str, bool]:
        """Fetch a URL and return (html, success)."""
        try:
            resp = await client.get(url)
            if resp.status_code >= 400:
                logger.debug("HTTP %d for %s", resp.status_code, url)
                return "", False
            return resp.text, True
        except httpx.HTTPError as exc:
            logger.debug("Fetch error for %s: %s", url, exc)
            return "", False

    def _parse_page(self, html: str, base_url: str) -> Tuple[str, str, List[str]]:
        """Extract text, title, and links from HTML."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")

            # Extract title
            title_tag = soup.find("title")
            title = title_tag.get_text(strip=True) if title_tag else ""

            # Remove script/style noise
            for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
                tag.decompose()

            text = soup.get_text(separator=" ", strip=True)

            # Extract and normalize links
            links: List[str] = []
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                    continue
                absolute = urljoin(base_url, href)
                normalized = self._normalize_url(absolute)
                if normalized:
                    links.append(normalized)

            return text, title, links
        except Exception as exc:  # noqa: BLE001
            logger.debug("Parse error for %s: %s", base_url, exc)
            return "", "", []

    def _score_content(self, text: str) -> Tuple[int, List[str], int, List[str], Optional[str]]:
        """Score page text for scholarship relevance + regional boost.

        Returns (base_score, matched_keywords, regional_score, regional_keywords, state_restriction).
        """
        if not text:
            return 0, [], 0, [], None
        lower = text.lower()

        # Base content keywords
        matched = [kw for kw in CONTENT_KEYWORDS if kw in lower]
        base_score = len(matched)

        # Regional scoring
        regional_keywords: List[str] = []

        # Check target states
        for state in REGIONAL_FILTERS["target_states"]:
            if state in lower:
                regional_keywords.append(state)

        # Check target counties
        for county in REGIONAL_FILTERS["target_counties"]:
            if county in lower:
                regional_keywords.append(county)

        # Check local context terms
        for term in REGIONAL_FILTERS["local_context_terms"]:
            if term in lower:
                regional_keywords.append(term)

        regional_score = len(regional_keywords) * REGIONAL_BOOST_PER_HIT

        # Top-20 metro area detection — award a +4 boost when candidate page
        # text matches any top-20 county or metro keyword, and attach detected
        # metro keys to regional_keywords so downstream LLM prompts receive
        # localized residency context.
        metro_slugs = detect_all_metros(text)
        if metro_slugs:
            regional_score += METRO_BOOST
            for slug in metro_slugs:
                metro_label = f"metro:{metro_name(slug)}"
                if metro_label not in regional_keywords:
                    regional_keywords.append(metro_label)

        # Extract state restriction if a clear residency requirement is found
        state_restriction = self._extract_state_restriction(lower)

        return base_score, matched, regional_score, regional_keywords, state_restriction

    @staticmethod
    def _extract_state_restriction(text_lower: str) -> Optional[str]:
        """Detect explicit state residency requirements in page text.

        Looks for patterns like "residents of Ohio", "Pennsylvania residents",
        "must be an Ohio resident", etc. Returns the 2-letter state code or None.
        """
        # Patterns that indicate a residency requirement
        residency_patterns = [
            r"residents?\s+of\s+(ohio|pennsylvania)",
            r"(ohio|pennsylvania)\s+residents?",
            r"must\s+be\s+(?:an?\s+)?(ohio|pennsylvania)\s+resident",
            r"resident\s+of\s+(ohio|pennsylvania)",
            r"(ohio|pennsylvania)\s+residency",
            r"must\s+reside\s+in\s+(ohio|pennsylvania)",
            r"living\s+in\s+(ohio|pennsylvania)",
        ]
        for pattern in residency_patterns:
            match = re.search(pattern, text_lower)
            if match:
                state_name = match.group(1)
                return _STATE_NAME_TO_CODE.get(state_name)

        # Also check for explicit 2-letter codes near "resident", "residency", or "living in"
        # Note: text_lower is already lowercase, so match lowercase codes and convert
        code_patterns = [
            r"residents?\s+of\s+\b(oh|pa)\b",
            r"\b(oh|pa)\b\s+residents?",
            r"must\s+be\s+(?:an?\s+)?\b(oh|pa)\b\s+resident",
            r"\b(oh|pa)\b\s+residency",
            r"residency\s+(?:in\s+)?\b(oh|pa)\b",
            r"living\s+in\s+\b(oh|pa)\b",
            r"reside\s+in\s+\b(oh|pa)\b",
        ]
        for pattern in code_patterns:
            match = re.search(pattern, text_lower)
            if match:
                return match.group(1).upper()

        return None

    def _should_follow(self, url: str, parent_url: str) -> bool:
        """Decide whether to follow a link based on heuristics."""
        # Reject bad file extensions
        path = urlparse(url).path.lower()
        for ext in REJECTED_EXTENSIONS:
            if path.endswith(ext):
                return False

        # Reject non-http(s)
        scheme = urlparse(url).scheme
        if scheme not in ("http", "https"):
            return False

        # Reject blocked mega-aggregator domains
        url_domain = self._get_domain(url)
        if url_domain in BLOCKED_DOMAINS:
            return False

        # Reject negative path patterns (non-grant pages)
        for pattern in NEGATIVE_PATH_PATTERNS:
            if pattern in path:
                return False

        parent_domain = self._get_domain(parent_url)

        # Always follow internal links (unless blocked above)
        if url_domain == parent_domain:
            return True

        # For external links, only follow if path contains a keyword
        path_lower = path.lower()
        return any(kw in path_lower for kw in PATH_KEYWORDS)

    @staticmethod
    def _normalize_url(url: str) -> Optional[str]:
        """Normalize a URL — strip fragments, ensure scheme."""
        if not url or not url.strip():
            return None
        url = url.strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return None
        # Strip fragment
        return parsed._replace(fragment="").geturl()

    @staticmethod
    def _get_domain(url: str) -> str:
        """Extract the registered domain (netloc without www.)."""
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
