"""C1 catalog-correctness regression tests.

Covers the audit findings fixed in Catalog Batch C1:
  - canonical credential vocabulary (UI labels vs scraper codes)
  - inference safety (ordinary prose cannot create hard gates)
  - LLM null-integrity (varies award -> NULL; yearless deadline -> NULL)
  - fabricated-title removal + generic listing heading rejection
  - amount/date parser hardening (years are not amounts; no fabricated years)
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from scrapers.llm_parser import (
    SYSTEM_PROMPT,
    _canonicalize_credentials,
    _sanitize_award_amount,
)
from scrapers.parsers.deterministic import (
    parse_apha,
    parse_aacn,
    parse_generic_scholarship,
)
from scrapers.schema import ScholarshipExtract
from scrapers.utils.credentials import (
    credential_token_set,
    credential_tokens,
    normalize_credential,
)
from scrapers.utils.normalize import (
    map_credentials,
    map_disciplines,
    parse_amount,
    parse_date,
)
from app.services.matcher import _credential_match, is_discipline_eligible


# ---------------------------------------------------------------------------
# Shared lightweight profile/scholarship mocks (same shape as test_matcher.py)
# ---------------------------------------------------------------------------

def _make_profile(**kwargs):
    defaults = {
        "id": "00000000-0000-0000-0000-000000000001",
        "disciplines": [],
        "target_credentials": [],
        "primary_discipline": None,
        "target_credential": None,
        "clinical_phase": None,
        "gpa": None,
        "state_residence": None,
        "metro_area": None,
        "sai_score": None,
        "first_gen": False,
        "minority_flag": False,
        "professional_affiliations": [],
        "hobbies": [],
        "subscription_tier": "free",
    }
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_scholarship(**kwargs):
    obj = MagicMock()
    obj.eligible_disciplines = kwargs.get("eligible_disciplines", [])
    obj.eligible_credentials = kwargs.get("eligible_credentials", [])
    obj.academic_levels = kwargs.get("academic_levels", [])
    return obj


# ---------------------------------------------------------------------------
# C1-A: Canonical credential vocabulary
# ---------------------------------------------------------------------------

class TestCredentialNormalization:
    def test_ui_label_maps_to_code(self):
        assert normalize_credential("Doctor of Pharmacy (PharmD)") == "PharmD"
        assert normalize_credential("Doctor of Medicine (MD)") == "MD"
        assert normalize_credential("Master of Public Health (MPH)") == "MPH"
        assert normalize_credential("Bachelor of Science in Nursing (BSN)") == "BSN"
        assert normalize_credential("Physician Assistant Studies (MPAS/MSPA)") == "PA"
        assert normalize_credential("Speech-Language Pathology (MS-SLP)") == "MS_SLP"
        assert normalize_credential("Doctor of Dental Surgery / Medicine (DDS/DMD)") == "DDS_DMD"

    def test_code_variants_normalize(self):
        assert normalize_credential("PharmD") == "PharmD"
        assert normalize_credential("Pharm.D.") == "PharmD"
        assert normalize_credential("pharmd") == "PharmD"
        assert normalize_credential("MD") == "MD"
        assert normalize_credential("DMD") == "DDS_DMD"
        assert normalize_credential("LPN/LVN") == "LPN"

    def test_llm_degree_levels_normalize(self):
        assert normalize_credential("Bachelor") == "Bachelor"
        assert normalize_credential("bachelor") == "Bachelor"
        assert normalize_credential("Doctorate") == "Doctorate"
        assert normalize_credential("Master of Science") == "Master"
        assert normalize_credential("High School") == "High School"

    def test_unknown_credentials_not_guessed(self):
        assert normalize_credential("AANP member certification") is None
        assert normalize_credential("") is None
        assert normalize_credential(None) is None
        # Unknown strings still produce a verbatim token so identical
        # free-text values on both sides can match each other.
        assert credential_tokens("AANP member certification") == {"aanp member certification"}

    def test_degree_level_tokens_expand(self):
        assert credential_tokens("PharmD") == {"pharmd", "doctorate"}
        assert credential_tokens("BSN") == {"bsn", "bachelor"}
        assert credential_tokens("Doctorate") == {"doctorate"}


class TestCredentialHardGate:
    def test_ui_label_matches_scraper_code(self):
        """C1-A core fix: the real UI representation matches the code."""
        profile = _make_profile(target_credentials=["Doctor of Pharmacy (PharmD)"])
        scholarship = _make_scholarship(eligible_credentials=["PharmD"])
        assert is_discipline_eligible(profile, scholarship) is True

    def test_variant_forms_match(self):
        profile = _make_profile(target_credentials=["Pharm.D."])
        scholarship = _make_scholarship(eligible_credentials=["PharmD"])
        assert _credential_match(profile, scholarship) is True

    def test_unrelated_credentials_still_gated(self):
        profile = _make_profile(target_credentials=["Doctor of Pharmacy (PharmD)"])
        scholarship = _make_scholarship(eligible_credentials=["DDS"])
        assert is_discipline_eligible(profile, scholarship) is False

        profile = _make_profile(target_credentials=["BSN"])
        scholarship = _make_scholarship(eligible_credentials=["PharmD"])
        assert is_discipline_eligible(profile, scholarship) is False

    def test_degree_level_intersection(self):
        """A 'Doctorate' restriction accepts a PharmD candidate; 'Bachelor' does not."""
        profile = _make_profile(target_credentials=["Doctor of Pharmacy (PharmD)"])
        assert is_discipline_eligible(profile, _make_scholarship(eligible_credentials=["Doctorate"])) is True
        assert is_discipline_eligible(profile, _make_scholarship(eligible_credentials=["Bachelor"])) is False

    def test_multiple_credentials_or_logic(self):
        profile = _make_profile(target_credentials=["BSN", "Doctor of Pharmacy (PharmD)"])
        scholarship = _make_scholarship(eligible_credentials=["DPT", "PharmD"])
        assert is_discipline_eligible(profile, scholarship) is True

    def test_empty_restriction_unrestricted(self):
        profile = _make_profile(target_credentials=["Doctor of Pharmacy (PharmD)"])
        assert is_discipline_eligible(profile, _make_scholarship(eligible_credentials=[])) is True

    def test_no_user_credentials_unrestricted(self):
        profile = _make_profile(target_credentials=[])
        assert is_discipline_eligible(profile, _make_scholarship(eligible_credentials=["PharmD"])) is True

    def test_unknown_freeform_still_gates(self):
        """Unknown credentials are never guessed into unrelated codes."""
        profile = _make_profile(target_credentials=["Doctor of Pharmacy (PharmD)"])
        scholarship = _make_scholarship(eligible_credentials=["AANP member certification"])
        assert is_discipline_eligible(profile, scholarship) is False


# ---------------------------------------------------------------------------
# C1-B: Unsafe substring inference removed / bounded
# ---------------------------------------------------------------------------

class TestInferenceSafety:
    def test_prose_does_not_create_credentials(self):
        prose = (
            "Students learn about our donors who return each year. "
            "We do not require essays."
        )
        assert map_credentials(prose) == []

    def test_prose_does_not_create_disciplines(self):
        prose = (
            "Recipients learn leadership skills. Our donors return annually. "
            "Contact us to apply."
        )
        assert map_disciplines(prose) == []

    def test_explicit_eligibility_still_maps(self):
        assert map_credentials("Open to PharmD and MD candidates.") == ["MD", "PharmD"]
        assert map_disciplines("Applicants must be enrolled in a nursing program.") == ["nursing"]

    def test_generic_scholarship_parser_does_not_scan_full_page(self):
        """Ordinary prose outside the eligibility section cannot leak
        credentials/disciplines into hard gates."""
        html = """
        <html><body>
          <h1>Community Merit Award</h1>
          <p>Students learn about our donors who return each year.
             We do not require essays.</p>
        </body></html>
        """
        extract = parse_generic_scholarship(html, "https://example.com/scholarships")
        assert extract.eligible_credentials == []
        assert extract.eligible_disciplines == []

    def test_llm_fallback_inference_removed(self):
        """The LLM path must not run keyword inference over page content."""
        import inspect

        import scrapers.llm_parser as lp

        src = inspect.getsource(lp.extract_with_llm)
        assert "map_credentials(" not in src
        assert "map_disciplines(" not in src


# ---------------------------------------------------------------------------
# C1-C: Null integrity
# ---------------------------------------------------------------------------

class TestNullIntegrity:
    def test_prompt_forbids_zero_award(self):
        assert "return 0" not in SYSTEM_PROMPT
        assert "never 0" in SYSTEM_PROMPT

    def test_prompt_forbids_year_inference(self):
        assert "next upcoming occurrence" not in SYSTEM_PROMPT
        assert "NEVER guess" in SYSTEM_PROMPT or "never guess" in SYSTEM_PROMPT.lower()

    def test_award_sanitize_guard(self):
        assert _sanitize_award_amount(0) is None
        assert _sanitize_award_amount(-500) is None
        assert _sanitize_award_amount(None) is None
        assert _sanitize_award_amount(5000) == 5000

    def test_credential_canonicalization(self):
        out = _canonicalize_credentials(
            ["pharmd", "Doctor of Medicine", "Unknown Custom Program"]
        )
        assert "PharmD" in out
        assert "MD" in out
        assert "Unknown Custom Program" in out  # preserved, not guessed


# ---------------------------------------------------------------------------
# C1-D: No fabricated titles / generic listing headings
# ---------------------------------------------------------------------------

class TestTitles:
    def test_deterministic_parsers_do_not_fabricate_titles(self):
        html = "<html><body><p>Some content with no heading.</p></body></html>"
        assert parse_apha(html, "https://aphanet.pharmacist.com/x").title == ""
        assert parse_aacn(html, "https://www.aacnnursing.org/x").title == ""
        extract = parse_generic_scholarship(html, "https://example.com/scholarships")
        assert extract.title == ""

    def test_generic_listing_headings_rejected(self):
        for bad in [
            "Scholarships",
            "Scholarship Opportunities",
            "Financial Aid",
            "Grants",
            "Funding Opportunities",
            "Outside Scholarships",
            "Apply",
        ]:
            assert ScholarshipExtract(title=bad).is_critical_complete() is False

    def test_specific_titles_accepted(self):
        for good in [
            "Community Health Merit Scholarship",
            "HSF Scholars Program",
            "Alice Grant Fund",
        ]:
            assert ScholarshipExtract(title=good).is_critical_complete() is True

    def test_nav_landmark_heading_is_not_an_opportunity_title(self):
        """E1 regression: nav/header landmarks rendered as h1/h2 (e.g. 'Main
        Navigation') must not become opportunity titles — real page produced
        a verified 'Main Navigation' record before boilerplate stripping."""
        html = """
        <html><body>
          <header><h1>Site Header</h1></header>
          <nav><h1>Main Navigation</h1><ul><li>Home</li></ul></nav>
          <main><h1>General Scholarship Fund</h1>
            <h2>Eligibility</h2><p>Open to residents.</p></main>
          <footer><h2>Contact</h2></footer>
        </body></html>
        """
        extract = parse_generic_scholarship(html, "https://example.org/scholarships")
        assert extract.title == "General Scholarship Fund"
        extract = parse_aacn(html, "https://www.aacnnursing.org/x")
        assert extract.title == "General Scholarship Fund"


# ---------------------------------------------------------------------------
# C1-E: Amount / date parser hardening
# ---------------------------------------------------------------------------

class TestParseAmount:
    def test_year_prefixed_currency(self):
        assert parse_amount("2025-2026 award: $5,000") == 5000

    def test_standard_amounts(self):
        assert parse_amount("$5,000") == 5000
        assert parse_amount("Up to $10,000") == 10000
        assert parse_amount("$2,500 per year") == 2500

    def test_bare_numbers(self):
        assert parse_amount("5000") == 5000
        assert parse_amount("Award of 1500") == 1500

    def test_years_are_not_amounts(self):
        assert parse_amount("2025") is None
        assert parse_amount("2026") is None
        assert parse_amount("Award year 2025-2026") is None

    def test_currency_anchored_year_sized_amount_allowed(self):
        # A real $2,025 award has a currency anchor and must be kept.
        assert parse_amount("$2,025") == 2025

    def test_zero_and_unknown(self):
        assert parse_amount("$0") is None
        assert parse_amount("varies") is None
        assert parse_amount("") is None
        assert parse_amount(None) is None

    def test_multiplier(self):
        assert parse_amount("2 x $5,000") == 5000


class TestParseDate:
    def test_complete_dates_parse(self):
        assert parse_date("March 1, 2026") == date(2026, 3, 1)
        assert parse_date("2026-03-01") == date(2026, 3, 1)
        assert parse_date("03/15/2027") == date(2027, 3, 15)
        assert parse_date("1 March 2026") == date(2026, 3, 1)

    def test_yearless_dates_return_none(self):
        assert parse_date("March 1") is None
        assert parse_date("March 1st") is None
        assert parse_date("Dec 15") is None

    def test_year_only_and_seasons_return_none(self):
        assert parse_date("Spring 2026") is None
        assert parse_date("Fall 2026 deadline") is None

    def test_rolling_and_unknown(self):
        assert parse_date("rolling") is None
        assert parse_date("varies") is None
        assert parse_date("") is None
        assert parse_date(None) is None

    def test_relative_terms(self):
        assert parse_date("today") == date.today()
