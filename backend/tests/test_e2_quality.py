"""Batch E2 — real-world catalog-quality guards.

Regression coverage for findings from the 61-source E2 cohort:
- donation/transaction links must never become application portal URLs;
- bare org/section headings are not opportunity titles (needs_review);
- garbled generic providers flag needs_review;
- asserted ['any'] disciplines require unrestricted-field evidence;
- verified records and honest fallbacks are unaffected.
"""

from __future__ import annotations

from unittest.mock import patch

import asyncio

from scrapers.extraction import attach_verification, extract_page
from scrapers.schema import ScholarshipExtract
from scrapers.utils.page_links import accept_url, link_index
from tests.c5_fixtures import fake_llm_factory


URL = "https://cf.example.org/scholarships/"


def _extract(**kw) -> ScholarshipExtract:
    return ScholarshipExtract(**kw)


def _verify(ex: ScholarshipExtract, text: str) -> ScholarshipExtract:
    return attach_verification(ex, text=text, source_url=URL)


# ---------------------------------------------------------------------------
# Donation/transaction portal rejection
# ---------------------------------------------------------------------------

DONATE_HTML = """
<html><body>
<h1>Community Foundation Scholarships</h1>
<p>Our scholarships support students in every field of study.</p>
<a href="https://cf.example.org/erp/donate/create/fund?funit_id=42">Give to this fund</a>
<a href="/scholarships/alpha">Apply for the Alpha Scholarship</a>
</body></html>
"""


class TestDonationPortalRejection:
    def test_donate_path_rejected_as_portal(self):
        links = link_index(DONATE_HTML, URL)
        assert accept_url("https://cf.example.org/erp/donate/create/fund?funit_id=42",
                          base_url=URL, links=links) is None

    def test_application_path_still_accepted(self):
        links = link_index(DONATE_HTML, URL)
        assert accept_url("https://cf.example.org/scholarships/alpha",
                          base_url=URL, links=links) == \
            "https://cf.example.org/scholarships/alpha"

    def test_checkout_and_give_paths_rejected(self):
        links = link_index(DONATE_HTML, URL)
        for u in ("https://cf.example.org/checkout/x",
                  "https://cf.example.org/give/now",
                  "https://cf.example.org/donate",
                  "https://cf.example.org/cart/items"):
            assert accept_url(u, base_url=URL, links=links) is None

    def test_donation_suffix_product_pages_rejected(self):
        """RTDNA regression: e-commerce "…-one-time-donation" product pages
        are donation endpoints, not application portals (E3 finding)."""
        links = link_index(DONATE_HTML, URL)
        for u in ("https://rtdna.org/products/ed-bradley-scholarship-one-time-donation",
                  "https://cf.example.org/products/give-now-donation",
                  "https://cf.example.org/fund/contribute-now-checkout"):
            assert accept_url(u, base_url=URL, links=links) is None

    def test_donation_suffix_does_not_overmatch(self):
        links = link_index(DONATE_HTML, URL)
        for u in ("https://cf.example.org/scholarships/alpha",
                  "https://drpepper.com/tuition/giveaway",
                  "https://cf.example.org/apply-for-scholarship"):
            assert accept_url(u, base_url=URL,
                              links={**links, u: u}) == u

    def test_extracted_donate_url_falls_back_to_source_page(self):
        """Alaska-CF regression: a per-fund donate link must not be stored
        as the apply portal; the authoritative listing page stands in."""
        scripts = {URL: [{"title": "Alpha Scholarship Fund",
                          "provider": "Example Community Foundation",
                          "portal_url": "https://cf.example.org/erp/donate/create/fund?funit_id=42"}]}
        calls = []
        with patch("scrapers.llm_parser.extract_opportunities_with_llm",
                   fake_llm_factory(scripts, calls)):
            page = asyncio.run(extract_page(DONATE_HTML, URL,
                                            provider_hint="Example Community Foundation"))
        assert len(page.extracts) == 1
        assert page.extracts[0].portal_url == URL


# ---------------------------------------------------------------------------
# Structural needs_review flags
# ---------------------------------------------------------------------------

class TestStructuralReviewFlags:
    def test_org_heading_title_flags_review(self):
        ex = _extract(title="Iowa Department of Education",
                      provider="Iowa Department of Education Homepage")
        out = _verify(ex, "Iowa Department of Education financial aid homepage")
        assert out.verification_status == "needs_review"

    def test_generic_provider_flags_review(self):
        ex = _extract(title="Loan-for-Service Programs", provider="Loan")
        out = _verify(ex, "LOAN-FOR-SERVICE PROGRAMS for state residents")
        assert out.verification_status == "needs_review"

    def test_any_disciplines_without_evidence_flags_review(self):
        ex = _extract(title="Annual Leadership Challenge",
                      provider="Example Honor Society",
                      eligible_disciplines=["any"])
        out = _verify(ex, "Annual Leadership Challenge for chapter members")
        assert out.verification_status == "needs_review"

    def test_any_disciplines_with_evidence_stays_verified(self):
        ex = _extract(title="Open Merit Scholarship",
                      provider="Example Foundation",
                      eligible_disciplines=["any"])
        text = ("Open Merit Scholarship awarded to students in any field "
                "of study at an accredited institution.")
        out = _verify(ex, text)
        assert out.verification_status == "verified"

    def test_normal_record_stays_verified(self):
        ex = _extract(title="Pharmacy Merit Scholarship",
                      provider="Example Pharmacy Association",
                      eligible_disciplines=["pharmacy"])
        out = _verify(ex, "Pharmacy Merit Scholarship for pharmacy students")
        assert out.verification_status == "verified"

    def test_empty_disciplines_not_flagged(self):
        ex = _extract(title="Community Service Award",
                      provider="Example Foundation")
        out = _verify(ex, "Community Service Award for volunteers")
        assert out.verification_status == "verified"
