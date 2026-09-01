"""Dry-run test for the focused web crawler.

Crawls a single seed URL (or a small set) without saving to the database,
printing discovered candidates with their relevance scores and matched keywords.

Usage:
    python -m scripts.test_crawler                          # uses default seed
    python -m scripts.test_crawler --url https://example.com  # single URL
    python -m scripts.test_crawler --max-depth 1            # shallow crawl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Add backend dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers.crawler import ScholarshipCrawler

logger = logging.getLogger("scripts.test_crawler")

DEFAULT_SEED = "https://www.aacp.org/student-awards"


async def run_test(seeds: list[str], max_depth: int, max_pages: int) -> None:
    crawler = ScholarshipCrawler(
        seeds=seeds,
        max_depth=max_depth,
        max_pages_per_domain=max_pages,
    )
    candidates = await crawler.crawl()
    stats = crawler.get_stats()

    print("\n" + "=" * 70)
    print("CRAWL DRY-RUN RESULTS")
    print("=" * 70)
    print(f"  Seeds:              {len(seeds)}")
    print(f"  Max depth:          {max_depth}")
    print(f"  Max pages/domain:   {max_pages}")
    print(f"  Pages crawled:      {stats.pages_crawled}")
    print(f"  Links followed:     {stats.links_followed}")
    print(f"  Links rejected:     {stats.links_rejected}")
    print(f"  Candidates found:   {stats.candidates_found}")
    print(f"  Errors:             {stats.errors}")
    print(f"  Domains visited:    {len(stats.domains_visited)}")
    print(f"  Domains:            {', '.join(sorted(stats.domains_visited))}")
    print("=" * 70)

    if not candidates:
        print("\n  No relevant candidates found.")
        return

    print(f"\n  Top {min(len(candidates), 20)} candidate(s):")
    print("-" * 70)
    for i, c in enumerate(sorted(candidates, key=lambda x: -x.relevance_score)[:20], 1):
        print(f"  {i:>2}. [{c.relevance_score:>2} pts] {c.url}")
        print(f"      Title:    {c.title[:70]}")
        print(f"      Depth:    {c.depth}")
        print(f"      Keywords: {', '.join(c.matched_keywords[:8])}")
        print()

    # Full JSON output for programmatic inspection
    output = {
        "stats": stats.summary(),
        "candidates": [
            {
                "url": c.url,
                "title": c.title,
                "relevance_score": c.relevance_score,
                "matched_keywords": c.matched_keywords,
                "depth": c.depth,
                "seed_url": c.seed_url,
            }
            for c in sorted(candidates, key=lambda x: -x.relevance_score)
        ],
    }
    out_path = Path(__file__).resolve().parent.parent / "scrapers" / "crawl_results.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)
    print(f"  Full results written to: {out_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.test_crawler", description="Dry-run crawler test")
    parser.add_argument("--url", type=str, default=None, help="Single seed URL to crawl")
    parser.add_argument("--max-depth", type=int, default=2, help="Max crawl depth (default 2)")
    parser.add_argument("--max-pages", type=int, default=10, help="Max pages per domain (default 10)")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    seeds = [args.url] if args.url else [DEFAULT_SEED]
    asyncio.run(run_test(seeds, args.max_depth, args.max_pages))
    return 0


if __name__ == "__main__":
    sys.exit(main())
