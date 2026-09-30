"""Canonical field-of-study taxonomy for EdFintia (Catalog Batch C8).

Healthcare is a *subtree* of the general field-of-study taxonomy, not the
database boundary. Persisted values are canonical text codes — new fields of
study are added by extending this registry, never by schema migration.

Design rules:

- ``ANY_FIELD`` ("any") marks an explicitly unrestricted opportunity. An
  empty ``eligible_disciplines`` list means *unknown* — matching treats both
  as non-gating, but the distinction is preserved in the stored record.
- Canonical codes form a shallow tree: broad areas (``stem``, ``business``,
  ``health_professions``) are parents of specific disciplines
  (``biological_sciences``, ``nursing``).
- Scholarship-side expansion walks UP the tree only: an award restricted to
  ``health_professions`` admits a ``nursing`` student.
- Profile-side expansion adds ``_COMPAT_EDGES``: the pre-C8 mapping folded
  every science/health major into healthcare enum values (biology ->
  medicine). Those undergraduate majors keep their historically matched
  healthcare eligibility so existing healthcare matching behavior is
  preserved without distorting the taxonomy.
- Unknown strings are never guessed into a code. ``normalize_field_of_study``
  returns ``None`` for unmapped values; callers decide whether to keep the
  raw string (exact-match only) or drop it.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

ANY_FIELD = "any"

# ---------------------------------------------------------------------------
# Field-of-study registry: canonical code -> (parent, label)
# ---------------------------------------------------------------------------

# Areas (top level) and their children. Order is presentation-stable.
_AREA_CHILDREN: Dict[str, List[Tuple[str, str]]] = {
    "health_professions": [
        ("pharmacy", "Pharmacy"),
        ("medicine", "Medicine"),
        ("nursing", "Nursing"),
        ("dentistry", "Dentistry"),
        ("dental_hygiene", "Dental Hygiene"),
        ("physician_assistant", "Physician Assistant"),
        ("optometry", "Optometry"),
        ("veterinary_medicine", "Veterinary Medicine"),
        ("podiatry", "Podiatry"),
        ("chiropractic", "Chiropractic"),
        ("therapeutics_rehab", "Therapeutics & Rehabilitation"),
        ("diagnostic_imaging", "Diagnostic Imaging"),
        ("public_health_emergency", "Public Health & Emergency"),
        ("allied_health", "Allied Health"),
        ("medical_laboratory_science", "Medical Laboratory Science"),
    ],
    "stem": [
        ("biological_sciences", "Biological Sciences"),
        ("physical_sciences", "Physical Sciences"),
        ("environmental_science", "Environmental Science"),
        ("computer_science", "Computer Science"),
        ("engineering", "Engineering"),
        ("mathematics", "Mathematics"),
    ],
    "business": [
        ("accounting", "Accounting"),
        ("finance", "Finance"),
        ("business_administration", "Business Administration"),
        ("marketing", "Marketing"),
        ("economics", "Economics"),
    ],
    "education": [
        ("teaching_education", "Teaching & Education"),
        ("early_childhood_education", "Early Childhood Education"),
    ],
    "social_sciences": [
        ("psychology", "Psychology"),
        ("social_work", "Social Work"),
        ("sociology", "Sociology"),
        ("political_science", "Political Science"),
        ("criminal_justice", "Criminal Justice"),
    ],
    "humanities": [
        ("english_language", "English & Literature"),
        ("history", "History"),
        ("foreign_languages", "Foreign Languages"),
        ("philosophy", "Philosophy"),
        ("communications", "Communications"),
    ],
    "arts": [
        ("fine_arts", "Fine Arts"),
        ("music", "Music"),
        ("design", "Design"),
    ],
    "public_service": [
        ("public_administration", "Public Administration"),
    ],
    "trades_technical": [
        ("construction_trades", "Construction Trades"),
        ("automotive_technology", "Automotive Technology"),
        ("culinary_arts", "Culinary Arts"),
        ("aviation", "Aviation"),
        ("welding", "Welding"),
        ("cosmetology", "Cosmetology"),
    ],
    "agriculture": [
        ("animal_science", "Animal Science"),
        ("horticulture", "Horticulture"),
    ],
    "law": [
        ("paralegal_studies", "Paralegal Studies"),
    ],
}

_AREA_LABELS: Dict[str, str] = {
    "health_professions": "Health Professions",
    "stem": "STEM",
    "business": "Business",
    "education": "Education",
    "social_sciences": "Social Sciences",
    "humanities": "Humanities",
    "arts": "Arts",
    "public_service": "Public Service",
    "trades_technical": "Trades & Technical",
    "agriculture": "Agriculture",
    "law": "Law",
}

# canonical code -> (parent code or None, display label)
FIELD_OF_STUDY: Dict[str, Tuple[Optional[str], str]] = {
    **{area: (None, label) for area, label in _AREA_LABELS.items()},
    "interdisciplinary": (None, "Interdisciplinary / General Studies"),
    **{
        code: (area, label)
        for area, children in _AREA_CHILDREN.items()
        for code, label in children
    },
}

CANONICAL_FIELDS: Set[str] = set(FIELD_OF_STUDY)

# ---------------------------------------------------------------------------
# Aliases: normalized free text -> canonical code
# ---------------------------------------------------------------------------


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower()).strip()


_ALIASES: Dict[str, str] = {
    # --- Healthcare subtree (the six legacy enum codes map to themselves) ---
    "pharmacy": "pharmacy",
    "pre pharmacy": "pharmacy",
    "pharmacy pharmd": "pharmacy",
    "medicine": "medicine",
    "pre medicine": "medicine",
    "pre med": "medicine",
    "osteopathic medicine": "medicine",
    "medical student": "medicine",
    "nursing": "nursing",
    "pre nursing": "nursing",
    "dentistry": "dentistry",
    "dental": "dentistry",
    "pre dental": "dentistry",
    "dental hygiene": "dental_hygiene",
    "physician assistant": "physician_assistant",
    "pre physician assistant": "physician_assistant",
    "pre pa": "physician_assistant",
    "optometry": "optometry",
    "veterinary": "veterinary_medicine",
    "veterinary medicine": "veterinary_medicine",
    "pre veterinary": "veterinary_medicine",
    "pre vet": "veterinary_medicine",
    "podiatry": "podiatry",
    "chiropractic": "chiropractic",
    "therapeutics rehab": "therapeutics_rehab",
    "physical therapy": "therapeutics_rehab",
    "pre physical therapy": "therapeutics_rehab",
    "occupational therapy": "therapeutics_rehab",
    "pre occupational therapy": "therapeutics_rehab",
    "speech language pathology": "therapeutics_rehab",
    "athletic training": "therapeutics_rehab",
    "respiratory therapy": "therapeutics_rehab",
    "exercise science": "therapeutics_rehab",
    "kinesiology": "therapeutics_rehab",
    "rehabilitation": "therapeutics_rehab",
    "diagnostic imaging": "diagnostic_imaging",
    "radiology": "diagnostic_imaging",
    "radiologic": "diagnostic_imaging",
    "radiologic technology": "diagnostic_imaging",
    "sonography": "diagnostic_imaging",
    "imaging": "diagnostic_imaging",
    "public health": "public_health_emergency",
    "public health emergency": "public_health_emergency",
    "epidemiology": "public_health_emergency",
    "global health": "public_health_emergency",
    "emergency": "public_health_emergency",
    "emergency management": "public_health_emergency",
    "disaster": "public_health_emergency",
    "health administration": "public_health_emergency",
    "healthcare management": "public_health_emergency",
    "healthcare management administration": "public_health_emergency",
    "health informatics": "public_health_emergency",
    "health sciences": "health_professions",
    "allied health": "allied_health",
    "medical laboratory science": "medical_laboratory_science",
    "environmental health": "public_health_emergency",
    # --- STEM ---
    "stem": "stem",
    "biology": "biological_sciences",
    "biological sciences": "biological_sciences",
    "molecular cellular biology": "biological_sciences",
    "molecular": "biological_sciences",
    "cellular biology": "biological_sciences",
    "microbiology": "biological_sciences",
    "genetics": "biological_sciences",
    "neuroscience": "biological_sciences",
    "botany": "biological_sciences",
    "plant biology": "biological_sciences",
    "botany plant biology": "biological_sciences",
    "zoology": "biological_sciences",
    "ecology": "biological_sciences",
    "ecology evolutionary biology": "biological_sciences",
    "evolutionary biology": "biological_sciences",
    "chemistry": "physical_sciences",
    "biochemistry": "physical_sciences",
    "organic chemistry": "physical_sciences",
    "analytical chemistry": "physical_sciences",
    "physics": "physical_sciences",
    "biophysics": "physical_sciences",
    "astronomy": "physical_sciences",
    "astrophysics": "physical_sciences",
    "astronomy astrophysics": "physical_sciences",
    "geology": "physical_sciences",
    "geology earth science": "physical_sciences",
    "earth science": "physical_sciences",
    "geophysics": "physical_sciences",
    "oceanography": "physical_sciences",
    "atmospheric": "physical_sciences",
    "meteorology": "physical_sciences",
    "atmospheric sciences meteorology": "physical_sciences",
    "physical sciences": "physical_sciences",
    "environmental science": "environmental_science",
    "computer science": "computer_science",
    "cs": "computer_science",
    "software engineering": "computer_science",
    "information technology": "computer_science",
    "it": "computer_science",
    "data science": "computer_science",
    "cybersecurity": "computer_science",
    "engineering": "engineering",
    "mechanical engineering": "engineering",
    "electrical engineering": "engineering",
    "civil engineering": "engineering",
    "chemical engineering": "engineering",
    "biomedical engineering": "engineering",
    "aerospace engineering": "engineering",
    "mathematics": "mathematics",
    "math": "mathematics",
    "statistics": "mathematics",
    "applied mathematics": "mathematics",
    # --- Business ---
    "business": "business",
    "business administration": "business_administration",
    "business management": "business_administration",
    "management": "business_administration",
    "accounting": "accounting",
    "accountancy": "accounting",
    "finance": "finance",
    "financial": "finance",
    "marketing": "marketing",
    "economics": "economics",
    # --- Education ---
    "education": "education",
    "teaching": "teaching_education",
    "teaching education": "teaching_education",
    "teacher education": "teaching_education",
    "education major": "teaching_education",
    "early childhood": "early_childhood_education",
    "early childhood education": "early_childhood_education",
    # --- Social sciences ---
    "social sciences": "social_sciences",
    "psychology": "psychology",
    "social work": "social_work",
    "sociology": "sociology",
    "political science": "political_science",
    "criminal justice": "criminal_justice",
    "criminology": "criminal_justice",
    "anthropology": "social_sciences",
    # --- Humanities ---
    "humanities": "humanities",
    "english": "english_language",
    "english literature": "english_language",
    "literature": "english_language",
    "history": "history",
    "foreign languages": "foreign_languages",
    "languages": "foreign_languages",
    "philosophy": "philosophy",
    "communications": "communications",
    "communication": "communications",
    "journalism": "communications",
    # --- Arts ---
    "arts": "arts",
    "fine arts": "fine_arts",
    "art": "fine_arts",
    "music": "music",
    "design": "design",
    "graphic design": "design",
    "theater": "fine_arts",
    "theatre": "fine_arts",
    "film": "fine_arts",
    # --- Public service ---
    "public service": "public_service",
    "public administration": "public_administration",
    "public policy": "public_administration",
    # --- Trades & technical ---
    "trades": "trades_technical",
    "trades technical": "trades_technical",
    "trade school": "trades_technical",
    "vocational": "trades_technical",
    "vocational technical": "trades_technical",
    "construction": "construction_trades",
    "construction trades": "construction_trades",
    "automotive": "automotive_technology",
    "automotive technology": "automotive_technology",
    "culinary": "culinary_arts",
    "culinary arts": "culinary_arts",
    "aviation": "aviation",
    "welding": "welding",
    "cosmetology": "cosmetology",
    "electrician": "construction_trades",
    "hvac": "construction_trades",
    # --- Agriculture ---
    "agriculture": "agriculture",
    "agricultural": "agriculture",
    "animal science": "animal_science",
    "horticulture": "horticulture",
    # --- Law ---
    "law": "law",
    "pre law": "law",
    "legal studies": "law",
    "paralegal": "paralegal_studies",
    "paralegal studies": "paralegal_studies",
    # --- General ---
    "interdisciplinary": "interdisciplinary",
    "general studies": "interdisciplinary",
    "undecided": "interdisciplinary",
    "liberal arts": "interdisciplinary",
    "any": ANY_FIELD,
    "any field": ANY_FIELD,
    "any major": ANY_FIELD,
    "any discipline": ANY_FIELD,
    "any field of study": ANY_FIELD,
    "all majors": ANY_FIELD,
    "all fields": ANY_FIELD,
    "all fields of study": ANY_FIELD,
    "all disciplines": ANY_FIELD,
    "all areas of study": ANY_FIELD,
}

# Profile-side compatibility edges (C8): fields of study that historically
# normalized into healthcare enum codes keep that eligibility. A biology
# major matched medicine-restricted awards before C8 and still does.
_COMPAT_EDGES: Dict[str, Set[str]] = {
    "biological_sciences": {"medicine"},
    "physical_sciences": {"medicine"},
    "environmental_science": {"public_health_emergency"},
    "medical_laboratory_science": {"medicine"},
    "dental_hygiene": {"medicine"},
    "allied_health": {"medicine"},
}


# Scope qualifiers: "all fields of pharmacy", "all pharmacy fields",
# "any major in nursing" restrict to a subtree — they must resolve to that
# field's code BEFORE the unrestricted aliases below can substring-match the
# "all fields"/"all majors" part (E2.5).
_SCOPE_QUALIFIER_RES = [
    re.compile(
        r"\b(?:any|all|every|each)\s+(?:accredited\s+)?fields?\s+of\s+"
        r"([a-z0-9 /&\-]{2,60})"),
    re.compile(
        r"\b(?:any|all|every|each)\s+(?:accredited\s+)?"
        r"(?:majors?|disciplines?)\s+in\s+([a-z0-9 /&\-]{2,60})"),
    re.compile(
        r"\b(?:any|all|every|each)\s+(?:accredited\s+)?"
        r"([a-z0-9 /&\-]{2,40}?)\s+fields?\b"),
]
_SCOPED_UNMAPPED = object()  # a scope phrase whose qualifier isn't canonical


def _scoped_field(text: str):
    """Resolve "all fields of X" to X's canonical code.

    Returns the code, ``_SCOPED_UNMAPPED`` when the qualifier is present but
    unrecognized (caller must treat as unknown, never ``any``), or ``None``
    when no scope phrase is present."""
    for pat in _SCOPE_QUALIFIER_RES:
        match = pat.search(text)
        if not match:
            continue
        qualifier = match.group(1).strip()
        for cand in re.split(r"\s+(?:and|or)\s+", qualifier):
            canon = normalize_field_of_study(cand)
            if canon and canon != ANY_FIELD:
                return canon
        return _SCOPED_UNMAPPED
    return None


def normalize_field_of_study(value: str) -> Optional[str]:
    """Normalize a free-form field/discipline label to a canonical code.

    Returns ``ANY_FIELD`` for explicit-unrestricted values, the canonical code
    for recognized values, and ``None`` for unrecognized input — callers must
    not guess a code for unknown strings.
    """
    if not value:
        return None
    text = _key(value)
    if not text:
        return None
    # Canonical codes are snake_case; _key() strips underscores to spaces.
    canon_form = text.replace(" ", "_")
    if canon_form in FIELD_OF_STUDY:
        return canon_form
    mapped = _ALIASES.get(text)
    if mapped:
        return mapped
    # "all fields of pharmacy" is a pharmacy restriction, not "any".
    scoped = _scoped_field(text)
    if scoped is _SCOPED_UNMAPPED:
        return None
    if scoped:
        return scoped
    # Prefix match: "pharmacy (pharmd)", "biology bs" style labels.
    for key, canon in _ALIASES.items():
        if len(key) >= 4 and (text.startswith(key) or key in text.split(" (")[0]):
            return canon
    return None


def _ancestors(code: str) -> Set[str]:
    out: Set[str] = set()
    node = FIELD_OF_STUDY.get(code)
    while node and node[0] and node[0] not in out:
        out.add(node[0])
        node = FIELD_OF_STUDY.get(node[0])
    return out


def _canon_or_raw(raw: str) -> str:
    canon = normalize_field_of_study(raw)
    if canon is not None:
        return canon
    return _key(raw)


def _field_pair_match(s_code: str, u_code: str) -> bool:
    """Direction-aware field match for one scholarship code vs one profile code.

    - ``s == u``: same field.
    - ``s`` is an ancestor of ``u``: the user studies a specialization of the
      allowed field (``health_professions`` award, ``nursing`` student).
    - ``u`` is an ancestor of ``s``: the user picked only the broad area —
      under-specified users are never hard-gated (a ``nursing`` award is not
      hidden from a ``health_professions`` profile).
    Sibling codes (``nursing`` vs ``pharmacy``) do NOT match — expanding both
    sides to ancestor sets would collide on the shared parent.
    """
    if s_code == u_code:
        return True
    if s_code in _ancestors(u_code):
        return True
    if u_code in _ancestors(s_code):
        return True
    return False


def scholarship_field_set(codes: Iterable[str]) -> Set[str]:
    """Normalize a scholarship's eligible_disciplines to canonical codes.

    ``ANY_FIELD`` is returned verbatim — the matcher checks for it
    separately. Unrecognized stored values degrade to exact-text comparison.
    """
    out: Set[str] = set()
    for raw in codes or []:
        canon = _canon_or_raw(str(raw))
        if canon:
            out.add(canon)
    return out


def profile_field_set(values: Iterable[str]) -> Set[str]:
    """Normalize profile disciplines/major labels to effective codes.

    Adds ``_COMPAT_EDGES`` as extra effective codes so legacy healthcare
    matching semantics (biology -> medicine, dental hygiene -> medicine) are
    preserved for profiles recorded under the old vocabulary. ``any`` on the
    profile side carries no restriction info and is dropped.
    """
    out: Set[str] = set()
    for raw in values or []:
        canon = _canon_or_raw(str(raw))
        if not canon or canon == ANY_FIELD:
            continue
        out.add(canon)
        out |= _COMPAT_EDGES.get(canon, set())
    return out


def fields_match(scholarship_codes: Iterable[str], profile_values: Iterable[str]) -> bool:
    """True when any scholarship field code matches any profile field code
    under the direction-aware pair rule."""
    s_set = scholarship_field_set(scholarship_codes)
    u_set = profile_field_set(profile_values)
    return any(_field_pair_match(s, u) for s in s_set for u in u_set)


def field_label(code: str) -> str:
    node = FIELD_OF_STUDY.get(code)
    return node[1] if node else code


# ---------------------------------------------------------------------------
# Funding type vocabulary
# ---------------------------------------------------------------------------

FUNDING_TYPES: Set[str] = {
    "scholarship",
    "grant",
    "fellowship",
    "tuition_reimbursement",
    "employer_sponsorship",
    "loan_repayment",
    "service_contingent",
    "prize",
    "other",
}

_FUNDING_ALIASES: Dict[str, str] = {
    "award": "scholarship",
    "scholarship award": "scholarship",
    "merit award": "scholarship",
    "need based scholarship": "scholarship",
    "grant": "grant",
    "fellowship": "fellowship",
    "assistantship": "fellowship",
    "traineeship": "fellowship",
    "tuition assistance": "tuition_reimbursement",
    "tuition benefit": "employer_sponsorship",
    "employer benefit": "employer_sponsorship",
    "employer education benefit": "employer_sponsorship",
    "education benefit": "employer_sponsorship",
    "employee benefit": "employer_sponsorship",
    "loan repayment": "loan_repayment",
    "loan forgiveness": "loan_repayment",
    "lrp": "loan_repayment",
    "service contingent": "service_contingent",
    "service commitment": "service_contingent",
    "service award": "service_contingent",
    "forgivable loan": "service_contingent",
    "contest": "prize",
    "sweepstakes": "prize",
    "stipend": "scholarship",
}


def normalize_funding_type(value: Optional[str]) -> Optional[str]:
    """Normalize a funding-type string to the canonical vocabulary.

    Recognized values become their canonical code; unrecognized non-empty
    strings return ``"other"`` (kept, not guessed); empty input returns
    ``None`` — unknown funding type stays unknown rather than defaulting to
    ``scholarship``.
    """
    if not value:
        return None
    text = _key(value).replace(" ", "_")
    if text in FUNDING_TYPES:
        return text
    aliased = _FUNDING_ALIASES.get(_key(value))
    if aliased:
        return aliased
    return "other"


# Explicit loan-forgiveness / loan-repayment language in an authoritative
# title or label establishes the funding mechanism on its own (E1.5).
_LOAN_REPAYMENT_TERMS = re.compile(
    r"\b(loan[\s-]*forgiveness|forgiveness\s+program|loan[\s-]*repayment|"
    r"student\s+loan\s+repayment|education(?:al)?\s+loan\s+repayment|"
    r"loan[\s-]*for[\s-]*service)\b", re.I)


def explicit_funding_type_in_text(text: Optional[str]) -> Optional[str]:
    """Return a canonical funding type asserted by explicit title/label text.

    Only the loan-forgiveness family is inferred this way — the terms are
    unambiguous funding mechanisms, not provider/category hints. Anything
    else returns ``None`` (unknown stays unknown).
    """
    if text and _LOAN_REPAYMENT_TERMS.search(text):
        return "loan_repayment"
    return None


# E4.6: an OFFICIAL program title whose head noun (last word, ignoring a
# trailing "(ACRONYM)" or "Program") names the instrument establishes it:
# "Paul Tsongas Scholarship", "Massachusetts Cash Grant", "AMS Graduate
# Fellowship". Deliberately narrow — plurals ("... Scholarships") are
# category/listing headings, a bare noun has no program identity, mixed
# instruments ("Fellowship Grant") and loan/internship/award wording are
# ambiguous, and compounds ("MASSGrant") are not the noun. Everything else
# stays unknown.
_TITLE_INSTRUMENT_NOUNS = {
    "scholarship": "scholarship",
    "grant": "grant",
    "fellowship": "fellowship",
}
_TITLE_TRAILING_QUALIFIER = re.compile(r"\s*(?:\([^()]*\)|\bprograms?\b)\s*$", re.I)
_TITLE_AMBIGUOUS_TERMS = re.compile(
    r"\b(loans?|internships?|awards?|prizes?|contests?|competitions?|stipends?|"
    r"scholarships|grants|fellowships)\b", re.I)


def funding_type_from_program_title(title: Optional[str]) -> Optional[str]:
    """Funding type established by an official program title, else None.

    The explicit loan-forgiveness family (``explicit_funding_type_in_text``)
    keeps precedence; otherwise only the title's own head noun counts.
    Never reads prose, navigation, marketing copy, or organization names —
    callers pass the program title only.
    """
    explicit = explicit_funding_type_in_text(title)
    if explicit or not title:
        return explicit
    core = " ".join(title.split())
    while True:
        stripped = _TITLE_TRAILING_QUALIFIER.sub("", core)
        if stripped == core:
            break
        core = stripped
    words = re.findall(r"[A-Za-z]+", core)
    if len(words) < 2:
        return None
    ftype = _TITLE_INSTRUMENT_NOUNS.get(words[-1].lower())
    if ftype is None or _TITLE_AMBIGUOUS_TERMS.search(core):
        return None
    if any(_TITLE_INSTRUMENT_NOUNS.get(w.lower(), ftype) != ftype for w in words[:-1]):
        return None
    return ftype


# E4.6: provider-type vocabulary is free text (no schema enum). Federal
# government sponsors get an explicit value instead of being mislabeled
# 'national_association'; state agencies already use 'state_agency'.
FEDERAL_AGENCY = "federal_agency"
_FEDERAL_PROVIDER_ALIASES = frozenset({
    "federal_agency", "federal", "federal_government", "federal_government_agency",
    "us_government", "u_s_government", "us_federal_government", "government_federal",
})


def normalize_provider_type(value: Optional[str]) -> Optional[str]:
    """Map federal-government spellings to ``federal_agency``; any other
    value passes through unchanged (no guessing, no reclassification)."""
    if not value or not value.strip():
        return None
    key = re.sub(r"[^a-z]+", "_", value.strip().lower()).strip("_")
    return FEDERAL_AGENCY if key in _FEDERAL_PROVIDER_ALIASES else value.strip()


# ---------------------------------------------------------------------------
# Additional eligibility vocabularies (C8)
# ---------------------------------------------------------------------------

CITIZENSHIP_REQUIREMENTS: Set[str] = {
    "us_citizen",
    "us_citizen_or_permanent_resident",
    "permanent_resident",
    "daca_eligible",
    "refugee_asylee",
    "international_eligible",
}

_CITIZENSHIP_ALIASES: Dict[str, str] = {
    "us citizen": "us_citizen",
    "u s citizen": "us_citizen",
    "united states citizen": "us_citizen",
    "citizen": "us_citizen",
    "citizenship": "us_citizen",
    "us citizen or permanent resident": "us_citizen_or_permanent_resident",
    "citizen or permanent resident": "us_citizen_or_permanent_resident",
    "citizen or national": "us_citizen_or_permanent_resident",
    "permanent resident": "permanent_resident",
    "green card": "permanent_resident",
    "daca": "daca_eligible",
    "daca eligible": "daca_eligible",
    "refugee": "refugee_asylee",
    "asylee": "refugee_asylee",
    "international": "international_eligible",
    "international students": "international_eligible",
    "international eligible": "international_eligible",
}


def normalize_citizenship(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = _key(value).replace(" ", "_")
    if text in CITIZENSHIP_REQUIREMENTS:
        return text
    return _CITIZENSHIP_ALIASES.get(_key(value))


ENROLLMENT_STATUSES: Set[str] = {
    "full_time",
    "part_time",
    "enrolled",
    "accepted",
    "graduating",
}

_ENROLLMENT_ALIASES: Dict[str, str] = {
    "full time": "full_time",
    "fulltime": "full_time",
    "full time enrollment": "full_time",
    "part time": "part_time",
    "parttime": "part_time",
    "enrolled": "enrolled",
    "currently enrolled": "enrolled",
    "matriculated": "enrolled",
    "accepted": "accepted",
    "incoming": "accepted",
    "senior": "graduating",
    "graduating": "graduating",
    "graduating senior": "graduating",
}


def normalize_enrollment_statuses(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for raw in values or []:
        text = _key(str(raw)).replace(" ", "_")
        canon = text if text in ENROLLMENT_STATUSES else _ENROLLMENT_ALIASES.get(_key(str(raw)))
        if canon and canon not in out:
            out.append(canon)
    return out


MILITARY_AFFILIATIONS: Set[str] = {
    "veteran",
    "active_duty",
    "reservist",
    "national_guard",
    "military_spouse",
    "military_dependent",
    "rotc",
}

_MILITARY_ALIASES: Dict[str, str] = {
    "veteran": "veteran",
    "veterans": "veteran",
    "active duty": "active_duty",
    "activeduty": "active_duty",
    "service member": "active_duty",
    "servicemember": "active_duty",
    "military": "active_duty",
    "armed forces": "active_duty",
    "reserve": "reservist",
    "reservist": "reservist",
    "national guard": "national_guard",
    "guard": "national_guard",
    "spouse": "military_spouse",
    "military spouse": "military_spouse",
    "dependent": "military_dependent",
    "military dependent": "military_dependent",
    "military family": "military_dependent",
    "gold star": "military_dependent",
    "rotc": "rotc",
}


def normalize_military_affiliation(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = _key(value).replace(" ", "_")
    if text in MILITARY_AFFILIATIONS:
        return text
    return _MILITARY_ALIASES.get(_key(value))


def normalize_scope(value: Optional[str]) -> Optional[str]:
    """Canonical geographic scope or ``None`` when unknown/unstated.

    ``None`` is the unknown marker — the system must never manufacture
    ``national`` for a program whose geography was not established.
    """
    if not value:
        return None
    text = _key(value).replace(" ", "_")
    return text if text in {"national", "state", "metro", "county", "city"} else None
