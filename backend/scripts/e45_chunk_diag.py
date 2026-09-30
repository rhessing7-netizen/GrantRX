"""E4.5 read-only diagnosis of listing-chunk planning for one source URL."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from bs4 import BeautifulSoup  # noqa: E402

from scrapers import extraction as E  # noqa: E402
from scrapers import llm_parser  # noqa: E402
from scrapers.fetcher import FetchSession  # noqa: E402
from scrapers.utils.normalize import clean_text  # noqa: E402
from scrapers.verification import html_to_text  # noqa: E402


async def main(url, save=None):
    r = await FetchSession().get(url)
    html = r.text or ""
    if save:
        open(save, "w", encoding="utf-8").write(html)
    cls = E.classify_page(html, url)
    text = html_to_text(html)
    print(f"fetch={r.outcome} html={len(html)} kind={cls.kind} text_chars={len(text)} "
          f"listing_window={llm_parser.LISTING_MAX_CHARS}")
    lim = E.ExtractionLimits.from_env()
    frags, planned = E._listing_chunk_fragments(
        html, max_chars=lim.chunk_max_chars, max_chunks=lim.max_chunks_per_page)
    sizes = [len(clean_text(BeautifulSoup(f, "html.parser").get_text(" "))) for f in frags]
    print(f"chunk_max_chars={lim.chunk_max_chars} chunks={len(frags)} planned={planned} sizes={sizes}")
    soup = E._content_soup(html)
    print({t: len(soup.find_all(t)) for t in ("h1", "h2", "h3", "h4", "h5", "dt", "li", "p", "table")})


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
