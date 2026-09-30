"""Catalog Batch C8 — general taxonomy tests.

Covers: canonical field-of-study registry, legacy healthcare alias
compatibility, unknown-vs-unrestricted semantics, funding types, credential
vocabulary, parent-program tracks, matching behavior, and the C6.5
null-list coercion staying intact.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scrapers.utils import taxonomy
from scrapers.utils.taxonomy import (
    ANY_FIELD,
    normalize_citizenship,
    normalize_enrollment_statuses,
    normalize_field_of_study,
    normalize_funding_type,
    normalize_military_affiliation,
    normalize_scope,
    profile_field_set,
    scholarship_field_set,
)
from scrapers.utils.credentials import (
    credential_requirement_set,
    credential_token_set,
    normalize_credential,
)
from scrapers.llm_parser import (
    LLMOpportunityList,
    llm_item_to_extract,
    _sanitize_disciplines,
)
from scrapers.schema import ScholarshipExtract, TrackExtract
from scrapers.extraction import title_on_page
from scrapers.runner import _canonical_disciplines, _to_db_dict
from scrapers.sources import normalize_discipline
from app.services.matcher import is_discipline_eligible


def _profile(**kw):
    p = MagicMock()
    for k, v in dict(
        disciplines=[], target_credentials=[], primary_discipline=None,
        target_credential=None, clinical_phase=None, gpa=None,
        state_residence=None, metro_area=None, sai_score=None,
        first_gen=False, minority_flag=False, professional_affiliations=[],
    ).items():
        setattr(p, k, v)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def _sch(**kw):
    s = MagicMock()
    for k, v in dict(
        eligible_disciplines=[], eligible_credentials=[], academic_levels=[],
        state_restrictions=[], metro_restrictions=[], county_restrictions=[],
        city_restrictions=[], required_affiliations=[], matching_tags=[],
        funding_type=None, employment_required=False, has_service_commitment=False,
        citizenship_requirement=None, enrollment_statuses=[],
        institution_restrictions=[], military_affiliation_requirement=None,
        tracks=[],
    ).items():
        setattr(s, k, v)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# Canonical field-of-study registry
# ---------------------------------------------------------------------------


def test_legacy_healthcare_codes_are_canonical():
    for code in ("pharmacy", "medicine", "nursing", "therapeutics_rehab",
                 "diagnostic_imaging", "public_health_emergency"):
        assert normalize_field_of_study(code) == code


def test_healthcare_aliases_resolve():
    assert normalize_field_of_study("Pre-Pharmacy") == "pharmacy"
    assert normalize_field_of_study("Pre-Medicine") == "medicine"
    assert normalize_field_of_study("physical therapy") == "therapeutics_rehab"
    assert normalize_field_of_study("radiology") == "diagnostic_imaging"
    # Pre-C8 these collapsed to "any" or "medicine" — now real codes.
    assert normalize_field_of_study("dentistry") == "dentistry"
    assert normalize_field_of_study("Dental Hygiene") == "dental_hygiene"
    assert normalize_field_of_study("physician assistant") == "physician_assistant"


def test_non_healthcare_fields_supported():
    assert normalize_field_of_study("Computer Science") == "computer_science"
    assert normalize_field_of_study("engineering") == "engineering"
    assert normalize_field_of_study("accounting") == "accounting"
    assert normalize_field_of_study("pre-law") == "law"
    assert normalize_field_of_study("welding") == "welding"
    assert normalize_field_of_study("culinary arts") == "culinary_arts"


def test_unrecognized_field_is_none_never_guessed():
    assert normalize_field_of_study("underwater basket weaving") is None
    assert normalize_field_of_study("") is None
    assert normalize_field_of_study(None) is None


def test_any_marker():
    assert normalize_field_of_study("any") == ANY_FIELD
    assert normalize_field_of_study("Any Major") == ANY_FIELD


# ---------------------------------------------------------------------------
# Expansion semantics (matching sets)
# ---------------------------------------------------------------------------


def test_scholarship_area_covers_children():
    s = scholarship_field_set(["health_professions"])
    assert "health_professions" in s  # scholarship set carries the area


def test_profile_child_matches_parent_area_restriction():
    prof = _profile(disciplines=["nursing"])
    sch = _sch(eligible_disciplines=["health_professions"])
    assert is_discipline_eligible(prof, sch)


def test_broad_profile_not_gated_by_specific_restriction():
    prof = _profile(disciplines=["health_professions"])
    sch = _sch(eligible_disciplines=["nursing"])
    assert is_discipline_eligible(prof, sch)


def test_unrelated_fields_do_not_match():
    prof = _profile(disciplines=["accounting"])
    sch = _sch(eligible_disciplines=["nursing"])
    assert not is_discipline_eligible(prof, sch)


def test_legacy_healthcare_matching_preserved_via_compat_edges():
    # Biology major + medicine-restricted award: pre-C8 mapped biology ->
    # medicine; the compat edge preserves that behavior on the new codes.
    prof = _profile(disciplines=["Biology"])
    sch = _sch(eligible_disciplines=["medicine"])
    assert is_discipline_eligible(prof, sch)


def test_legacy_labels_on_both_sides_still_match():
    prof = _profile(disciplines=["pharmacy"])
    sch = _sch(eligible_disciplines=["pharmacy"])
    assert is_discipline_eligible(prof, sch)


def test_any_unrestricted_passes_everyone():
    prof = _profile(disciplines=["accounting"])
    assert is_discipline_eligible(prof, _sch(eligible_disciplines=["any"]))
    assert is_discipline_eligible(prof, _sch(eligible_disciplines=[]))


# ---------------------------------------------------------------------------
# Unknown vs unrestricted
# ---------------------------------------------------------------------------


def test_scope_unknown_is_null_not_national():
    ext = ScholarshipExtract(title="X")
    assert ext.scope is None
    rec = _to_db_dict(ext)
    assert rec["scope"] is None


def test_scope_explicit_values_kept():
    assert normalize_scope("national") == "national"
    assert normalize_scope("state") == "state"
    assert normalize_scope("garbage") is None
    assert normalize_scope(None) is None


def test_llm_scope_unstated_stays_null():
    item = LLMOpportunityList.model_validate({"opportunities": [{
        "title": "Minnesota RN Loan Forgiveness", "provider": "MDH",
    }]}).opportunities[0]
    assert item.scope is None
    ext = llm_item_to_extract(item, "https://example.org/x")
    assert ext.scope is None


def test_llm_scope_explicit_national_kept():
    item = LLMOpportunityList.model_validate({"opportunities": [{
        "title": "X", "provider": "P", "scope": "national",
    }]}).opportunities[0]
    assert llm_item_to_extract(item, "https://e.org").scope == "national"


def test_funding_type_unknown_is_null():
    ext = ScholarshipExtract(title="X")
    assert ext.funding_type is None
    assert _to_db_dict(ext)["funding_type"] is None


def test_funding_type_normalized():
    assert normalize_funding_type("loan forgiveness") == "loan_repayment"
    assert normalize_funding_type("Tuition Assistance") == "tuition_reimbursement"
    assert normalize_funding_type("fellowship") == "fellowship"
    assert normalize_funding_type("grant") == "grant"
    assert normalize_funding_type(None) is None
    assert normalize_funding_type("mystery mechanism") == "other"


def test_eligible_disciplines_empty_vs_any_distinct():
    # Both pass the gate, but persisted semantics differ: [] = unknown,
    # ['any'] = explicitly unrestricted.
    assert _canonical_disciplines([]) == []
    assert _canonical_disciplines(["any"]) == ["any"]
    assert _canonical_disciplines(["Biology", "bogus field"]) == ["biological_sciences"]
    assert _canonical_disciplines(["any", "nursing"]) == ["any"]


def test_is_general_major_persists_any_marker():
    item = LLMOpportunityList.model_validate({"opportunities": [{
        "title": "X", "provider": "P", "is_general_major": True,
    }]}).opportunities[0]
    ext = llm_item_to_extract(item, "https://e.org")
    assert ext.eligible_disciplines == ["any"]


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def test_general_credentials_added():
    assert normalize_credential("Juris Doctor") == "JD"
    assert normalize_credential("JD") == "JD"
    assert normalize_credential("Master of Business Administration") == "MBA"
    assert normalize_credential("Doctor of Education") == "EdD"
    assert normalize_credential("Master of Arts") == "Master"


def test_asymmetric_degree_matching_preserved():
    # PharmD satisfies generic "Doctorate"; DDS restriction does not accept PharmD.
    assert "doctorate" in credential_token_set(["PharmD"])
    assert not (credential_token_set(["PharmD"]) & credential_requirement_set(["DDS"]))
    assert credential_token_set(["JD"]) & credential_requirement_set(["Doctorate"])


# ---------------------------------------------------------------------------
# Eligibility dimensions (record-only)
# ---------------------------------------------------------------------------


def test_eligibility_dims_normalize():
    assert normalize_citizenship("U.S. citizen") == "us_citizen"
    assert normalize_citizenship("DACA") == "daca_eligible"
    assert normalize_citizenship(None) is None
    assert normalize_enrollment_statuses(["full time", "enrolled", "bogus"]) == ["full_time", "enrolled"]
    assert normalize_military_affiliation("veterans") == "veteran"
    assert normalize_military_affiliation("military spouse") == "military_spouse"


def test_llm_dims_flow_to_extract():
    item = LLMOpportunityList.model_validate({"opportunities": [{
        "title": "Vets Award", "provider": "P",
        "citizenship_requirement": "us_citizen",
        "enrollment_statuses": ["full_time"],
        "institution_restrictions": ["University of Minnesota"],
        "military_affiliation_requirement": "veteran",
    }]}).opportunities[0]
    ext = llm_item_to_extract(item, "https://e.org")
    assert ext.citizenship_requirement == "us_citizen"
    assert ext.enrollment_statuses == ["full_time"]
    assert ext.institution_restrictions == ["University of Minnesota"]
    assert ext.military_affiliation_requirement == "veteran"
    rec = _to_db_dict(ext)
    assert rec["citizenship_requirement"] == "us_citizen"
    assert rec["military_affiliation_requirement"] == "veteran"


def test_record_only_dims_surface_as_notices_not_gates():
    from app.services.matcher import score_scholarship
    prof = _profile()
    sch = _sch(
        citizenship_requirement="us_citizen",
        military_affiliation_requirement="veteran",
        institution_restrictions=["State U"],
        enrollment_statuses=["full_time"],
    )
    score, missing = score_scholarship(prof, sch)
    assert score > 0  # never gated
    text = " ".join(missing).lower()
    assert "citizenship" in text and "military" in text
    assert "institution" in text and "enrollment" in text


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------


def test_track_extract_schema():
    t = TrackExtract(title="Registered Nurse", detail_url="https://e.org/rn",
                     award_amount=10000, deadline="2027-01-01",
                     eligible_disciplines=["nursing"])
    assert t.title == "Registered Nurse"


def test_llm_tracks_flow_to_extract():
    item = LLMOpportunityList.model_validate({"opportunities": [{
        "title": "MN Loan Forgiveness", "provider": "P",
        "tracks": [
            {"title": "Registered Nurse", "detail_url": "https://e.org/rn",
             "award_amount": 9000, "eligible_disciplines": ["nursing"]},
            {"title": "Physician", "detail_url": "https://e.org/md"},
        ],
    }]}).opportunities[0]
    ext = llm_item_to_extract(item, "https://e.org")
    assert len(ext.tracks) == 2
    assert ext.tracks[0].award_amount == 9000
    assert ext.tracks[0].eligible_disciplines == ["nursing"]


def test_blank_track_titles_dropped():
    item = LLMOpportunityList.model_validate({"opportunities": [{
        "title": "X", "provider": "P",
        "tracks": [{"title": ""}, {"title": "Real Track"}],
    }]}).opportunities[0]
    ext = llm_item_to_extract(item, "https://e.org")
    assert [t.title for t in ext.tracks] == ["Real Track"]


def test_tracks_not_in_db_dict():
    # Tracks persist via _sync_tracks, never as a scholarships column.
    ext = ScholarshipExtract(title="X", tracks=[TrackExtract(title="T")])
    assert "tracks" not in _to_db_dict(ext)


def test_null_list_coercion_still_intact():
    # C6.5: null list fields must not sink the item (now incl. new dims/tracks).
    item = LLMOpportunityList.model_validate({"opportunities": [{
        "title": "X", "provider": "P",
        "eligible_disciplines": None,
        "academic_levels": None,
        "enrollment_statuses": None,
        "institution_restrictions": None,
        "tracks": None,
    }]}).opportunities[0]
    ext = llm_item_to_extract(item, "https://e.org")
    assert ext.eligible_disciplines == []
    assert ext.tracks == []


def test_title_on_page_guard_reusable_for_tracks():
    text = "Our program offers Registered Nurse and Physician tracks."
    assert title_on_page("Registered Nurse", text)
    assert not title_on_page("Pharmacist", text)


def test_source_hint_normalize_discipline_canonical():
    assert normalize_discipline("dentistry") == "dentistry"
    assert normalize_discipline("unmapped xyzzy") == "any"


# ---------------------------------------------------------------------------
# API schema compatibility
# ---------------------------------------------------------------------------


def test_scholarshipout_accepts_non_enum_disciplines():
    from app.schemas.schemas import ScholarshipOut
    import uuid as _uuid
    s = ScholarshipOut(
        id=_uuid.uuid4(), title="X", provider="P", portal_url="https://e.org",
        eligible_disciplines=["computer_science", "any"],
    )
    assert s.eligible_disciplines == ["computer_science", "any"]
    assert s.scope is None  # unknown by default now
    assert s.funding_type is None


# ---------------------------------------------------------------------------
# FIELD_OF_STUDY acyclicity (final-E2E defect: self-parented root codes hung
# _ancestors -> match_scholarships -> the matched feed request)
# ---------------------------------------------------------------------------


def test_field_of_study_is_acyclic():
    from scrapers.utils.taxonomy import FIELD_OF_STUDY, _ancestors

    for code in FIELD_OF_STUDY:
        # _ancestors must terminate for every code in the taxonomy
        anc = _ancestors(code)
        assert code not in anc, f"{code} is its own ancestor"
        # full parent walk must terminate too
        seen = {code}
        node = FIELD_OF_STUDY.get(code)
        while node and node[0]:
            assert node[0] not in seen, f"cycle via {code}: {node[0]}"
            seen.add(node[0])
            node = FIELD_OF_STUDY.get(node[0])


def test_area_codes_remain_valid_match_codes():
    from scrapers.utils.taxonomy import (
        fields_match,
        normalize_field_of_study,
    )

    # The removed self-children were redundant: the area code itself must
    # still be canonical so "agriculture"/"law" restrictions keep working.
    assert normalize_field_of_study("agriculture") == "agriculture"
    assert normalize_field_of_study("law") == "law"
    assert fields_match(["agriculture"], ["animal_science"]) is True
    assert fields_match(["law"], ["paralegal_studies"]) is True
    assert fields_match(["law"], ["nursing"]) is False


def test_ancestors_defensive_against_cycles():
    from scrapers.utils import taxonomy

    original = dict(taxonomy.FIELD_OF_STUDY)
    try:
        taxonomy.FIELD_OF_STUDY["e2e_cycle_a"] = ("e2e_cycle_b", "A")
        taxonomy.FIELD_OF_STUDY["e2e_cycle_b"] = ("e2e_cycle_a", "B")
        assert taxonomy._ancestors("e2e_cycle_a") == {"e2e_cycle_b", "e2e_cycle_a"}
    finally:
        for k in ("e2e_cycle_a", "e2e_cycle_b"):
            taxonomy.FIELD_OF_STUDY.pop(k, None)
        taxonomy.FIELD_OF_STUDY.update(original)
