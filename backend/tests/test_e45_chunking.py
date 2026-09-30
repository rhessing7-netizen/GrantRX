"""E4.5 bounded listing-chunk invariants.

E2.5 chunked only at h1-h3 boundaries and kept every leaf block whole, so a
single heading section or one giant <ul>/<table> larger than the chunk
bound became ONE unbounded chunk that the prompt window then silently
truncated. These tests pin: bounded chunks, deterministic coverage (every
item in exactly one chunk), items never cut, and context preservation.
"""

import re

from bs4 import BeautifulSoup

from scrapers.extraction import _listing_chunk_fragments
from scrapers.utils.normalize import clean_text

MAX = 2000


def _text_len(fragment: str) -> int:
    return len(clean_text(BeautifulSoup(fragment, "html.parser").get_text(" ")))


def _item(i: int) -> str:
    return f"Item {i:03d} Scholarship provides $1,000 to eligible students. " + "x" * 60


def _occurrences(frags, i):
    return sum(len(re.findall(rf"Item {i:03d} Scholarship", f)) for f in frags)


def test_giant_list_without_headings_is_bounded_and_complete():
    lis = "".join(f"<li>{_item(i)}</li>" for i in range(120))
    html = f"<html><body><h1>State Aid</h1><ul>{lis}</ul></body></html>"
    frags, planned = _listing_chunk_fragments(html, max_chars=MAX, max_chunks=50)
    assert planned == len(frags) > 1
    h1_len = _text_len("<h1>State Aid</h1>")
    assert all(_text_len(f) <= MAX + h1_len for f in frags)
    assert all(_occurrences(frags, i) == 1 for i in range(120))


def test_oversized_heading_section_is_subdivided_with_heading_context():
    ps = "".join(f"<p>{_item(i)}</p>" for i in range(80))
    html = f"<html><body><h1>Agency</h1><h2>Nursing Programs</h2>{ps}</body></html>"
    frags, _ = _listing_chunk_fragments(html, max_chars=MAX, max_chunks=50)
    assert len(frags) > 1
    assert all("Nursing Programs" in f for f in frags)
    assert all(_occurrences(frags, i) == 1 for i in range(80))


def test_table_split_at_row_boundaries_only():
    rows = "".join(f"<tr><td>{_item(i)}</td><td>Deadline March 1</td></tr>" for i in range(90))
    html = f"<html><body><h1>Grants</h1><table>{rows}</table></body></html>"
    frags, _ = _listing_chunk_fragments(html, max_chars=MAX, max_chunks=50)
    assert len(frags) > 1
    for f in frags:
        soup = BeautifulSoup(f, "html.parser")
        assert all(len(tr.find_all("td")) == 2 for tr in soup.find_all("tr"))
    assert all(_occurrences(frags, i) == 1 for i in range(90))


def test_definition_list_keeps_term_with_description():
    pairs = "".join(f"<dt>Program {i:03d}</dt><dd>{_item(i)}</dd>" for i in range(70))
    html = f"<html><body><h1>Aid</h1><dl>{pairs}</dl></body></html>"
    frags, _ = _listing_chunk_fragments(html, max_chars=MAX, max_chunks=50)
    assert len(frags) > 1
    for i in range(70):
        holder = [f for f in frags if f"Program {i:03d}<" in f]
        assert len(holder) == 1 and f"Item {i:03d} Scholarship" in holder[0]


def test_single_indivisible_item_is_never_cut():
    huge = "<li>Giant Scholarship " + "detail " * 600 + "END-MARK</li>"
    html = f"<html><body><h1>X</h1><ul><li>{_item(1)}</li>{huge}<li>{_item(2)}</li></ul></body></html>"
    frags, _ = _listing_chunk_fragments(html, max_chars=MAX, max_chunks=50)
    holder = [f for f in frags if "Giant Scholarship" in f]
    assert len(holder) == 1 and "END-MARK" in holder[0]
    assert _occurrences(frags, 1) == 1 and _occurrences(frags, 2) == 1


def test_small_sections_keep_existing_heading_packing():
    html = ("<html><body><h1>Two Awards</h1>"
            "<h3>Alpha Scholarship</h3><p>$1,000.</p>"
            "<h3>Beta Scholarship</h3><p>$2,000.</p></body></html>")
    frags, planned = _listing_chunk_fragments(html, max_chars=MAX, max_chunks=5)
    assert planned == 1 and len(frags) == 1
    assert "Alpha Scholarship" in frags[0] and "Beta Scholarship" in frags[0]


def test_chunk_cap_still_enforced_after_subdivision():
    lis = "".join(f"<li>{_item(i)}</li>" for i in range(300))
    html = f"<html><body><h1>Big</h1><ul>{lis}</ul></body></html>"
    frags, planned = _listing_chunk_fragments(html, max_chars=MAX, max_chunks=3)
    assert len(frags) == 3 and planned > 3
