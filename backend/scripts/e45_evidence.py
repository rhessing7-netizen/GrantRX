"""E4.5 read-only evidence probe via the compliant FetchSession.

Usage: python scripts/e45_evidence.py probes.json
probes.json: [{"label": ..., "url": ..., "patterns": ["regex", ...]}, ...]
Prints outcome/status and a bounded text window around each pattern hit.
No database access; honours robots/fetch policy of FetchSession.
"""
import asyncio
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scrapers.fetcher import FetchSession  # noqa: E402


def _plain(raw):
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw or "")
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)))


async def main(path):
    probes = json.load(open(path, encoding="utf-8"))
    s = FetchSession()
    for p in probes:
        r = await s.get(p["url"])
        print(f"== {p['label']} | {r.outcome} {r.http_status} | {(r.final_url or p['url'])[:100]}")
        text = _plain(r.text)
        for pat in p.get("patterns", []):
            hits = [m for m in re.finditer(pat, text, re.I)][: p.get("max_hits", 2)]
            if not hits:
                print(f"   [{pat}] (not found)")
            for m in hits:
                a, b = max(0, m.start() - 180), min(len(text), m.end() + 260)
                print(f"   [{pat}] ...{text[a:b]}...")


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    asyncio.run(main(sys.argv[1]))
