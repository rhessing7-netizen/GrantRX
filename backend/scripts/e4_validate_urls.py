"""E4 pre-registration URL validation (read-only).

Fetches each candidate source URL in ``scripts/e4_sources.json`` through the
compliant C6 FetchSession and reports the outcome. Nothing is persisted —
this exists only to catch typos/dead URLs BEFORE a source enters
sources.json / catalog_sources.

Usage:
    python -m scripts.e4_validate_urls [--file scripts/e4_sources.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def run(path: str) -> list[dict]:
    from scrapers.fetch_policy import FetchResult, OUTCOME_NETWORK_ERROR, default_session
    from scrapers.fetcher import fetch_result

    with open(path, "r", encoding="utf-8") as fh:
        candidates = json.load(fh)

    session = default_session()
    sem = asyncio.Semaphore(6)

    async def _one(item):
        async with sem:
            try:
                res = await fetch_result(
                    item["url"], scraper_type=item.get("scraper_type") or "deterministic",
                    session=session)
            except Exception as exc:  # noqa: BLE001
                res = FetchResult(url=item["url"], outcome=OUTCOME_NETWORK_ERROR,
                                  error=type(exc).__name__)
            return {
                "name": item["name"],
                "url": item["url"],
                "outcome": res.outcome,
                "http_status": res.http_status,
                "final_url": res.final_url,
                "bytes": len(res.text or ""),
            }

    results = await asyncio.gather(*(_one(i) for i in candidates))
    await session.aclose()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(prog="scripts.e4_validate_urls")
    parser.add_argument("--file", default=str(Path(__file__).parent / "e4_sources.json"))
    args = parser.parse_args()

    results = asyncio.run(run(args.file))
    ok = sum(1 for r in results if r["outcome"] == "ok")
    print(f"\n{'OUTCOME':<20}{'HTTP':<6}{'BYTES':<9}NAME")
    for r in sorted(results, key=lambda r: (r["outcome"] != "ok", r["name"])):
        flag = "" if r["outcome"] == "ok" else "  <-- REVIEW"
        print(f"{r['outcome']:<20}{str(r['http_status']):<6}{r['bytes']:<9}{r['name']}{flag}")
        if r["final_url"]:
            print(f"{'':<35}resolved: {r['final_url'][:90]}")
    print(f"\n{ok}/{len(results)} fetched OK")
    out_path = Path(__file__).parent / "e4_url_check.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"detail: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
