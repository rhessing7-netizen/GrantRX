from types import SimpleNamespace

from scrapers.runner import (
    _canonical_identity_url,
    _normalize_identity_text,
    _same_scholarship_identity,
)
from scrapers.schema import ScholarshipExtract


def _extract(title="Nursing Excellence Scholarship", provider="Example Foundation", url="https://example.org/scholarships/nursing"):
    return ScholarshipExtract(title=title, provider=provider, portal_url=url)


def test_canonical_url_ignores_tracking_fragment_www_and_trailing_slash():
    a = "https://www.example.org/scholarships/nursing/?utm_source=email#apply"
    b = "https://example.org/scholarships/nursing"
    assert _canonical_identity_url(a) == _canonical_identity_url(b)


def test_same_title_provider_survives_provider_url_migration():
    existing = SimpleNamespace(
        title="Nursing Excellence Scholarship",
        provider="Example Foundation",
        portal_url="https://old.example.org/2026/nursing",
    )
    assert _same_scholarship_identity(existing, _extract(url="https://apply.example.org/nursing-2027"))


def test_same_provider_different_scholarship_is_not_merged():
    existing = SimpleNamespace(
        title="Nursing Excellence Scholarship",
        provider="Example Foundation",
        portal_url="https://example.org/scholarships/nursing",
    )
    incoming = _extract(title="Pharmacy Excellence Scholarship", url="https://example.org/scholarships/pharmacy")
    assert not _same_scholarship_identity(existing, incoming)


def test_same_title_different_provider_is_not_merged_when_urls_differ():
    existing = SimpleNamespace(
        title="Healthcare Scholarship",
        provider="Foundation A",
        portal_url="https://a.example/scholarship",
    )
    incoming = _extract(title="Healthcare Scholarship", provider="Foundation B", url="https://b.example/scholarship")
    assert not _same_scholarship_identity(existing, incoming)


def test_identity_text_normalizes_case_punctuation_and_whitespace():
    assert _normalize_identity_text("  Smith-Jones  Scholarship! ") == "smith jones scholarship"
