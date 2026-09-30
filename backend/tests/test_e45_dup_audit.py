"""E4.5 duplicate-candidate detection (read-only reporting).

Pins the proven E4 miss patterns as detectable while guaranteeing that
exact identity keys are unchanged (no fuzzy merging) and that distinct
sibling programs on one listing page are not flagged HIGH.
"""

from types import SimpleNamespace as NS

from scrapers.utils.dup_audit import HIGH, LOW, MEDIUM, classify_pair, find_candidates, provider_core
from scrapers.utils.identity import compute_identity_keys


def _r(id, title, provider, portal, states=(), archive_reason=None):
    return NS(id=id, title=title, provider=provider, portal_url=portal,
              state_restrictions=list(states), archive_reason=archive_reason)


WI_A = _r("a", "Academic Excellence Scholarship", "Wisconsin Higher Educational Aids Board",
          "https://heab.state.wi.us/features/aes.html", ["WI"])
WI_B = _r("b", "Academic Excellence Scholarship", "Wisconsin Higher Educational Aids Board (HEAB)",
          "https://docs.legis.wisconsin.gov/statutes/statutes/39/III/41", ["WI"])


def test_provider_core_drops_parenthetical_only():
    assert provider_core("Wisconsin Higher Educational Aids Board (HEAB)") == provider_core(
        "Wisconsin Higher Educational Aids Board")
    assert provider_core("AMA Foundation") != provider_core("APhA Foundation")


def test_wi_statute_vs_program_page_is_high_candidate():
    c = classify_pair(WI_A, WI_B)
    assert c.tier == HIGH and "provider_core=" in c.signals


def test_identity_keys_still_do_not_merge_wi_pattern():
    """Detection only: exact identity must stay conservative."""
    a = set(filter(None, compute_identity_keys(WI_A.title, WI_A.provider, WI_A.portal_url)))
    b = set(filter(None, compute_identity_keys(WI_B.title, WI_B.provider, WI_B.portal_url)))
    assert not (a & b)


def test_administrator_vs_listing_site_same_state_is_medium():
    a = _r("a", "Next NC Scholarship", "College Foundation, Inc.",
           "https://www.cfnc.org/pay-for-college/next-nc-scholarship/", ["NC"])
    b = _r("b", "Next NC Scholarship", "UNC System", "https://nextncscholarship.org/", ["NC"])
    assert classify_pair(a, b).tier == MEDIUM


def test_same_generic_title_different_orgs_is_low():
    a = _r("a", "Graduate Student Scholarship", "American Speech-Language-Hearing Foundation",
           "https://www.ashfoundation.org/apply/graduate-student-scholarship/")
    b = _r("b", "Graduate Student Scholarship", "NSBE", "https://nsbe.org/scholarships/")
    assert classify_pair(a, b).tier == LOW


def test_sibling_programs_on_one_listing_are_not_candidates():
    a = _r("a", "Ohio Physicians of Tomorrow Scholarship", "AMA Foundation",
           "https://amafoundation.org/physicians-of-tomorrow")
    b = _r("b", "Illinois Physicians of Tomorrow Scholarship", "AMA Foundation",
           "https://amafoundation.org/physicians-of-tomorrow")
    assert classify_pair(a, b) is None
    assert find_candidates([a, b]) == []


def test_find_candidates_skips_already_archived_duplicates():
    archived = _r("c", WI_B.title, WI_B.provider, WI_B.portal_url, ["WI"], archive_reason="duplicate")
    assert find_candidates([WI_A, archived]) == []
    assert [c.tier for c in find_candidates([WI_A, WI_B])] == [HIGH]
