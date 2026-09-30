"""Safety tests for scholarship URL repair."""
from scripts.repair_urls import _is_specific_opportunity_url, _root_domain_url


def test_root_homepage_is_never_specific_opportunity():
    assert _root_domain_url("https://example.org/scholarships/nursing") == "https://example.org"
    assert not _is_specific_opportunity_url("https://example.org")
    assert not _is_specific_opportunity_url("https://example.org/")


def test_specific_scholarship_pages_are_eligible_replacements():
    assert _is_specific_opportunity_url("https://example.org/scholarships/nursing-award")
    assert _is_specific_opportunity_url("https://example.org/financial-aid/grants")
    assert _is_specific_opportunity_url("https://example.org/programs/loan-repayment")


def test_generic_provider_pages_are_not_repairs():
    assert not _is_specific_opportunity_url("https://example.org/about")
    assert not _is_specific_opportunity_url("https://example.org/students")
    assert not _is_specific_opportunity_url("https://example.org/programs")
