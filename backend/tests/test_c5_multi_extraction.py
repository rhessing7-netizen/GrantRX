"""C5 multi-opportunity extraction regression tests (fixtures A-J + guards).

All pages are local fixtures; the LLM and detail fetches are scripted. The
real classification, URL acceptance, evidence scoping, verification, C4
identity and C3 lifecycle code paths run unmodified.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

import scrapers.runner as runner
from app.services import lifecycle
from scrapers import extraction as ext
from scrapers.extraction import ExtractionLimits, classify_page, evidence_windows, extract_page
from scrapers.llm_parser import (
    SYSTEM_PROMPT,
    LLMOpportunityList,
    LLMScholarship,
    build_user_prompt,
)
from tests import c5_fixtures as fx
from tests.conftest import FakeCatalogSession


def _run(coro):
    return asyncio.run(coro)


def _extract(html, url, scripts, *, fetch_pages=None, limits=None, llm_calls=None, fetch_calls=None):
    fetch = fx.fake_fetch_factory(fetch_pages, fetch_calls) if fetch_pages is not None else None
    with patch("scrapers.llm_parser.extract_opportunities_with_llm", fx.fake_llm_factory(scripts, llm_calls)):
        return _run(extract_page(html, url, limits=limits or ExtractionLimits(), fetch_detail=fetch))


def _ingest(db, page):
    from scrapers.fetch_policy import FetchResult

    async def _live(url, **kw):
        return FetchResult(url=url, outcome="ok", http_status=200)

    with patch.object(runner, "_check_url_result", _live):
        return [_run(runner._persist_extract(db, e, page.url, multi=page.is_multi)) for e in page.extracts]


def _listing(db=None, **kw):
    page = _extract(fx.listing_html(**{k: v for k, v in kw.items() if k in ("alpha_award", "beta_deadline", "include_delta", "hostile")}),
                    fx.LISTING_URL,
                    {fx.LISTING_URL: kw.get("items") or fx.listing_items(**{k: v for k, v in kw.items() if k in ("include_delta",)})},
                    fetch_pages=kw.get("fetch_pages", fx.DETAIL_PAGES))
    return page


def _by_title(page):
    return {e.title: e for e in page.extracts}


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassification:
    def test_listing(self):
        c = classify_page(fx.listing_html(), fx.LISTING_URL)
        assert c.kind == "listing" and len(c.items) >= 5

    def test_single_with_section_headings(self):
        assert classify_page(fx.SINGLE_HTML).kind == "single_opportunity"

    def test_irrelevant(self):
        # "Scholarships" appears only in navigation chrome.
        assert classify_page(fx.IRRELEVANT_HTML).kind == "irrelevant"

    def test_keyword_alone_does_not_make_listing(self):
        html = ("<html><body><h1>Scholarships</h1><p>We love scholarships. Scholarships "
                "change lives. Ask us about scholarships and financial aid.</p></body></html>")
        assert classify_page(html).kind != "listing"

    def test_page_builder_p_headings_detected_as_listing(self):
        # C6.5 calibration: Kadence/Elementor render card titles as <p>/<div>
        # with a heading class; plain "Learn More" links carry no name.
        card = ('<div class="card"><p class="kt-adv-heading wp-block-kadence-advancedheading">{t}</p>'
                "<p>Open Date 01/05/2027 Deadline 02/19/2027</p><a href='/x/{i}'>Learn More</a></div>")
        titles = ["Hand in Hand Research Grant", "Kielhofner Doctoral Research Scholarship",
                  "Nancy Talbot Postdoctoral Research Fellowship"]
        html = "<html><body><main>" + "".join(card.format(t=t, i=i) for i, t in enumerate(titles)) + "</main></body></html>"
        c = classify_page(html)
        assert c.kind == "listing" and len(c.items) == 3

    def test_heading_class_body_text_not_counted(self):
        # A long paragraph merely styled with a title class is not a named item.
        html = ('<html><body><h1>Harper Scholarship</h1><div class="entry-title">This scholarship '
                "supports nursing students across the region with tuition help each year and more</div>"
                "<p>Award $3,000. Deadline April 30, 2027.</p></body></html>")
        assert classify_page(html).kind == "single_opportunity"

    def test_two_named_items_with_repeated_facts_is_listing(self):
        html = ("<html><body><h3>Kappa Scholarship</h3><p>$1,000, deadline May 1</p>"
                "<h3>Lambda Grant</h3><p>$2,000, deadline June 1</p></body></html>")
        assert classify_page(html).kind == "listing"


# ---------------------------------------------------------------------------
# A. Single opportunity  /  irrelevant
# ---------------------------------------------------------------------------

class TestSingleAndIrrelevant:
    def test_A_single_page_one_extract_via_llm(self):
        page = _extract(fx.SINGLE_HTML, fx.SINGLE_URL, {fx.SINGLE_URL: fx.SINGLE_ITEMS})
        assert page.kind == "single_opportunity" and len(page.extracts) == 1
        e = page.extracts[0]
        assert e.portal_url == "https://harper.example.org/apply/clinical-excellence"
        assert e.verification_status == "verified"

    def test_A_single_page_deterministic_still_works(self):
        url = "https://harper.example.org/scholarships/clinical-excellence"
        page = _extract(fx.SINGLE_HTML, url, {})
        assert page.method == "deterministic" and len(page.extracts) == 1
        assert page.extracts[0].title == "Harper Clinical Excellence Scholarship"

    def test_irrelevant_page_yields_zero_without_llm_call(self):
        calls = []
        page = _extract(fx.IRRELEVANT_HTML, fx.IRRELEVANT_URL, {}, llm_calls=calls)
        assert page.kind == "irrelevant" and page.extracts == [] and calls == []

    def test_listing_never_consumed_by_deterministic_parser(self):
        # URL contains "scholarship" -> the generic deterministic parser matches,
        # but a listing must route to multi-extraction instead.
        page = _listing()
        assert page.method == "llm" and len(page.extracts) == 5


# ---------------------------------------------------------------------------
# B / C. Multi-opportunity listing, per-child URLs, identity
# ---------------------------------------------------------------------------

class TestListing:
    def test_B_distinct_children_and_null_integrity(self):
        page = _listing()
        t = _by_title(page)
        assert set(t) == {"Alpha Nursing Scholarship", "Beta Pharmacy Scholarship", "Gamma Memorial Fund",
                          "Delta Allied Health Award", "Epsilon Rural Medicine Grant"}
        assert t["Gamma Memorial Fund"].award_amount is None      # "varies" -> NULL
        assert t["Gamma Memorial Fund"].deadline is None          # rolling -> NULL
        # C8: explicitly unrestricted records ['any']; [] now means unknown.
        assert t["Gamma Memorial Fund"].eligible_disciplines == ["any"]  # general major
        assert t["Delta Allied Health Award"].deadline is None
        assert t["Beta Pharmacy Scholarship"].eligible_credentials == ["PharmD"]  # canonical
        # No page-wide fact copied onto siblings.
        assert t["Delta Allied Health Award"].eligible_credentials == []

    def test_B_per_child_url_resolution(self):
        t = _by_title(_listing())
        assert t["Alpha Nursing Scholarship"].portal_url == "https://apply.example-portal.com/riverbend/alpha"
        assert t["Alpha Nursing Scholarship"].detail_url == "https://riverbend.example.org/scholarships/alpha-nursing"
        # relative detail link resolved against the listing page
        assert t["Beta Pharmacy Scholarship"].portal_url == "https://riverbend.example.org/scholarships/beta-pharmacy"
        # no own link -> listing URL (weak identity)
        assert t["Gamma Memorial Fund"].portal_url == fx.LISTING_URL
        for e in t.values():
            assert e.source_url == fx.LISTING_URL

    def test_hallucinated_url_rejected(self):
        page = _listing()
        e = _by_title(page)["Epsilon Rural Medicine Grant"]
        assert e.portal_url == fx.LISTING_URL and e.detail_url is None
        assert page.urls_rejected == 1

    def test_B_C_identity_distinct_and_strong_where_available(self):
        db = FakeCatalogSession()
        page = _listing()
        assert _ingest(db, page) == ["created"] * 5
        keys = {r.title: r.identity_key for r in db.rows}
        assert len(set(keys.values())) == 5
        assert keys["Alpha Nursing Scholarship"] == "u:https://apply.example-portal.com/riverbend/alpha"
        assert keys["Beta Pharmacy Scholarship"] == "u:https://riverbend.example.org/scholarships/beta-pharmacy"
        # Shared listing URL + same provider + different titles -> tp identities.
        assert keys["Gamma Memorial Fund"] == "tp:gamma memorial fund|riverbend community foundation"
        assert keys["Epsilon Rural Medicine Grant"].startswith("tp:epsilon rural medicine grant|")

    def test_shared_apply_link_is_not_identity(self):
        html = ("<html><body><h3>Kappa Scholarship</h3><p>$1,000</p><h3>Lambda Scholarship</h3><p>$2,000</p>"
                "<h3>Mu Scholarship</h3><p>$3,000</p><a href='https://portal.example.com/apply'>Apply</a></body></html>")
        url = "https://kfund.example.org/awards"
        items = [dict(title=t, provider="K Fund", portal_url="https://portal.example.com/apply")
                 for t in ("Kappa Scholarship", "Lambda Scholarship", "Mu Scholarship")]
        page = _extract(html, url, {url: items})
        assert {e.portal_url for e in page.extracts} == {url}
        db = FakeCatalogSession()
        _ingest(db, page)
        assert len({r.identity_key for r in db.rows}) == 3


# ---------------------------------------------------------------------------
# D / E. Refresh and missing child
# ---------------------------------------------------------------------------

class TestRefresh:
    def test_D_refresh_updates_same_rows(self):
        db = FakeCatalogSession()
        _ingest(db, _listing())
        ids = {r.title: r.id for r in db.rows}
        page2 = _extract(fx.listing_html(alpha_award="$6,000", beta_deadline="June 30, 2027"), fx.LISTING_URL,
                         {fx.LISTING_URL: fx.listing_items(alpha_award=6000, beta_deadline="2027-06-30")},
                         fetch_pages=fx.DETAIL_PAGES)
        assert _ingest(db, page2) == ["updated"] * 5
        assert len(db.rows) == 5
        rows = {r.title: r for r in db.rows}
        assert {t: r.id for t, r in rows.items()} == ids
        assert rows["Alpha Nursing Scholarship"].award_amount == 6000
        assert str(rows["Beta Pharmacy Scholarship"].deadline) == "2027-06-30"
        assert rows["Alpha Nursing Scholarship"].verification_status == "verified"

    def test_E_missing_child_not_staled_or_archived(self):
        db = FakeCatalogSession()
        _ingest(db, _listing())
        delta = next(r for r in db.rows if r.title.startswith("Delta"))
        seen_before = delta.last_seen_at
        page2 = _extract(fx.listing_html(include_delta=False), fx.LISTING_URL,
                         {fx.LISTING_URL: fx.listing_items(include_delta=False)}, fetch_pages=fx.DETAIL_PAGES)
        _ingest(db, page2)
        assert len(db.rows) == 5
        assert lifecycle.current_status(delta) == "published"
        assert delta.consecutive_misses == 0 and delta.last_seen_at == seen_before


# ---------------------------------------------------------------------------
# F. Cross-child verification isolation
# ---------------------------------------------------------------------------

class TestVerificationIsolation:
    def test_F_correct_children_verify_independently(self):
        t = _by_title(_listing(fetch_pages={}))
        assert t["Alpha Nursing Scholarship"].verification_status == "verified"
        assert t["Beta Pharmacy Scholarship"].verified_fields["min_gpa"] == "verified"

    def test_F_sibling_facts_do_not_verify_another_child(self):
        items = fx.listing_items()
        # Extractor wrongly assigns Beta's award/deadline/GPA to Alpha.
        items[0].update(award_amount=10000, deadline="2027-06-15", min_gpa=3.5)
        page = _extract(fx.listing_html(), fx.LISTING_URL, {fx.LISTING_URL: items}, fetch_pages={})
        a = _by_title(page)["Alpha Nursing Scholarship"]
        assert a.verified_fields["award_amount"] == "unverified"
        assert a.verified_fields["deadline"] == "unverified"
        assert a.verified_fields["min_gpa"] == "unverified"
        assert a.verification_status == "needs_review"
        assert _by_title(page)["Beta Pharmacy Scholarship"].verification_status == "verified"

    def test_llm_cannot_self_certify(self):
        items = fx.listing_items()
        items[2]["verification_status"] = "verified"  # extra key from a compromised model
        page = _extract(fx.listing_html(), fx.LISTING_URL, {fx.LISTING_URL: items}, fetch_pages={})
        g = _by_title(page)["Gamma Memorial Fund"]
        assert g.verified_fields["award_amount"] == "not_asserted"  # NULL not falsely verified
        assert g.verification_status in ("verified", "needs_review")  # computed from evidence (title only)

    def test_evidence_windows_prefer_longer_title(self):
        text = "Alpha Scholarship II pays $9,000. Alpha Scholarship pays $1,000."
        w = evidence_windows(text, ["Alpha Scholarship", "Alpha Scholarship II"])
        assert "$1,000" in w[0] and "$9,000" not in w[0]
        assert "$9,000" in w[1]

    def test_inferred_deadline_year_dropped(self):
        items = fx.listing_items()
        items[3]["deadline"] = "2029-05-01"  # "announced each spring" -> invented year
        page = _extract(fx.listing_html(), fx.LISTING_URL, {fx.LISTING_URL: items}, fetch_pages={})
        assert _by_title(page)["Delta Allied Health Award"].deadline is None


# ---------------------------------------------------------------------------
# G / H. Generic headings and malformed siblings
# ---------------------------------------------------------------------------

class TestRejectionAndIsolation:
    def test_G_generic_headings_rejected(self):
        items = fx.listing_items() + [dict(title="Scholarships", provider=fx.PROVIDER),
                                      dict(title="Financial Aid", provider=fx.PROVIDER)]
        page = _extract(fx.listing_html(), fx.LISTING_URL, {fx.LISTING_URL: items}, fetch_pages={})
        assert len(page.extracts) == 5
        assert sum(1 for _, r in page.rejected if r == "generic_or_empty_title") == 2

    def test_H_malformed_item_dropped_siblings_survive(self):
        r = LLMOpportunityList.model_validate({"opportunities": [
            {"title": "Alpha Nursing Scholarship", "provider": "P"},
            {"title": "Beta Pharmacy Scholarship", "provider": "P", "award_amount": "a lot"},
            {"title": "Gamma Memorial Fund", "provider": "P"},
        ]})
        assert [o.title for o in r.opportunities] == ["Alpha Nursing Scholarship", "Gamma Memorial Fund"]
        assert r.invalid_items == 1

    def test_H_null_and_scalar_list_fields_do_not_sink_item(self):
        """C6.5 regression: gpt-4o-mini emits null (or a bare string) for list
        fields described as 'empty if none'. An explicit JSON null bypasses
        default_factory and previously failed validation, dropping the whole
        opportunity."""
        r = LLMOpportunityList.model_validate({"opportunities": [
            {"title": "Alpha Nursing Scholarship", "provider": "P",
             "eligible_credentials": None, "academic_levels": None,
             "eligible_disciplines": None, "matching_tags": None},
            {"title": "Beta Pharmacy Scholarship", "provider": "P",
             "eligible_credentials": "PharmD", "state_restrictions": "CA"},
        ]})
        assert r.invalid_items == 0
        alpha, beta = r.opportunities
        assert alpha.eligible_credentials == [] and alpha.academic_levels == []
        assert beta.eligible_credentials == ["PharmD"]
        assert beta.state_restrictions == ["CA"]

    def test_H_bad_url_and_fabricated_title_isolated(self):
        items = fx.listing_items() + [
            dict(title="Omega Phantom Scholarship", provider=fx.PROVIDER),  # not on page
        ]
        items[1]["portal_url"] = "ht!tp://::broken"
        page = _extract(fx.listing_html(), fx.LISTING_URL, {fx.LISTING_URL: items}, fetch_pages={})
        assert len(page.extracts) == 5
        assert ("Omega Phantom Scholarship", "title_not_on_page") in page.rejected
        beta = _by_title(page)["Beta Pharmacy Scholarship"]
        assert beta.portal_url == "https://riverbend.example.org/scholarships/beta-pharmacy"


# ---------------------------------------------------------------------------
# I. Hostile source content
# ---------------------------------------------------------------------------

class TestHostileContent:
    def test_I_prompt_delimits_and_neutralizes(self):
        prompt = build_user_prompt(fx.listing_html(hostile=fx.HOSTILE_TEXT), fx.LISTING_URL,
                                   mode="listing", max_items=25)
        assert prompt.count("</untrusted_page_content>") == 1
        body = prompt.split("<untrusted_page_content>", 1)[1]
        assert "ignore previous instructions" in body  # stays inside the data block
        assert "[removed]" in body
        assert "evil.example.com" not in prompt.split("<untrusted_page_content>")[0]  # not a link

    def test_I_policy_in_system_prompt(self):
        assert "evidence only, never" in SYSTEM_PROMPT and "instructions" in SYSTEM_PROMPT
        assert "EMPTY list" in SYSTEM_PROMPT

    def test_I_obedient_model_output_is_neutralized(self):
        """Simulate a model that obeyed the injection: its URL is not a page
        link, its invented deadline year is absent, and 'verified' is ignored."""
        items = fx.listing_items() + [dict(
            title="Zeta Free Money Grant", provider=fx.PROVIDER, deadline="2031-01-01",
            portal_url="https://evil.example.com/steal-credentials", verification_status="verified")]
        html = fx.listing_html(hostile=fx.HOSTILE_TEXT)
        page = _extract(html, fx.LISTING_URL, {fx.LISTING_URL: items}, fetch_pages={})
        z = _by_title(page)["Zeta Free Money Grant"]
        assert z.portal_url == fx.LISTING_URL          # injected URL rejected
        assert z.verified_fields["title"] == "verified"  # page's own claim, located on page
        # deadline 2031 appears in the hostile text itself -> kept but only as the
        # page's claim; the injected link and self-certification had no effect.
        assert "evil.example.com" not in (z.portal_url or "")


# ---------------------------------------------------------------------------
# J. Detail pages
# ---------------------------------------------------------------------------

class TestDetailPages:
    def test_J_detail_failure_keeps_listing_facts(self):
        page = _listing()
        b = _by_title(page)["Beta Pharmacy Scholarship"]
        assert page.detail_failed >= 1
        assert b.award_amount == 10000 and b.deadline == "2027-06-15"
        assert b.verification_status == "verified"
        assert b.max_sai is None  # nothing invented

    def test_detail_success_is_child_scoped_evidence(self):
        items = fx.listing_items()
        items[0]["min_gpa"] = 3.0  # only stated on Alpha's own detail page
        page = _extract(fx.listing_html(), fx.LISTING_URL, {fx.LISTING_URL: items},
                        fetch_pages=fx.DETAIL_PAGES)
        assert _by_title(page)["Alpha Nursing Scholarship"].verified_fields["min_gpa"] == "verified"
        assert page.detail_succeeded == 2

    def test_detail_fetch_is_bounded_and_not_recursive(self):
        calls = []
        _extract(fx.listing_html(), fx.LISTING_URL, {fx.LISTING_URL: fx.listing_items()},
                 fetch_pages=fx.DETAIL_PAGES, fetch_calls=calls,
                 limits=ExtractionLimits(max_detail_fetches_per_page=1))
        assert len(calls) == 1

    def test_detail_fetch_disabled(self):
        calls = []
        _extract(fx.listing_html(), fx.LISTING_URL, {fx.LISTING_URL: fx.listing_items()},
                 fetch_pages=fx.DETAIL_PAGES, fetch_calls=calls,
                 limits=ExtractionLimits(detail_fetch_enabled=False))
        assert calls == []


# ---------------------------------------------------------------------------
# Limits, lifecycle interplay, observability
# ---------------------------------------------------------------------------

class TestLimitsAndLifecycle:
    def test_max_opportunities_per_page(self):
        page = _extract(fx.listing_html(), fx.LISTING_URL, {fx.LISTING_URL: fx.listing_items()},
                        fetch_pages={}, limits=ExtractionLimits(max_opportunities_per_page=2))
        assert len(page.extracts) == 2
        assert sum(1 for _, r in page.rejected if r == "over_page_limit") == 3

    def test_listing_url_cannot_resurrect_dead_link_child(self):
        db = FakeCatalogSession()
        _ingest(db, _listing())
        gamma = next(r for r in db.rows if r.title == "Gamma Memorial Fund")
        lifecycle.archive(gamma, lifecycle.DEAD_LINK)
        _ingest(db, _listing())
        assert (gamma.lifecycle_status, gamma.archive_reason) == ("archived", "dead_link")

    def test_stats_summary(self):
        stats = ext.ExtractionStats()
        stats.add(_listing())
        stats.add(_extract(fx.IRRELEVANT_HTML, fx.IRRELEVANT_URL, {}))
        s = stats.summary()
        assert s["pages_listing"] == 1 and s["pages_irrelevant"] == 1
        assert s["opportunities_extracted"] == 5 and s["urls_rejected"] == 1
        assert s["detail_fetch_attempted"] == 3 and s["detail_fetch_failed"] == 1

    def test_limits_from_env(self, monkeypatch):
        monkeypatch.setenv("C5_MAX_OPPORTUNITIES_PER_PAGE", "7")
        monkeypatch.setenv("C5_DETAIL_FETCH_ENABLED", "false")
        lim = ExtractionLimits.from_env()
        assert lim.max_opportunities_per_page == 7 and lim.detail_fetch_enabled is False
