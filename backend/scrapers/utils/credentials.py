"""Canonical credential vocabulary shared by ingestion and matching.

The product historically compared `eligible_credentials` (scholarship side,
populated by scrapers/LLM with codes like ``PharmD``) against
``target_credentials`` (profile side, populated by the UI with labels like
``Doctor of Pharmacy (PharmD)``) using exact string equality.  The two
vocabularies never intersected, so any credential-restricted opportunity was
hard-gated for every user who picked a credential.

This module defines one canonical vocabulary plus a deterministic alias map:

    UI labels            -> canonical code
    short codes          -> canonical code
    LLM/free-form        -> canonical code (when recognized)

``credential_tokens(value)`` expands a canonical code to the token set used by
the matcher: the code itself plus its degree level (``bachelor``, ``master``,
``doctorate``, ...) so a scholarship that requires "Doctorate" matches a PharmD
candidate while a "BSN" restriction still gates them.

Unrecognized strings are preserved verbatim (normalized lowercase) so identical
free-text values on both sides still match, but an unknown credential is never
guessed into an unrelated canonical code.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Set

# ---------------------------------------------------------------------------
# Canonical codes and their degree levels
# ---------------------------------------------------------------------------

# canonical code -> degree-level token added to its match set
_LEVELS: Dict[str, str] = {
    # Doctoral / professional practice
    "PharmD": "doctorate",
    "MD": "doctorate",
    "DO": "doctorate",
    "DPT": "doctorate",
    "DNP": "doctorate",
    "DDS_DMD": "doctorate",
    "OTD": "doctorate",
    "OD": "doctorate",
    "DPM": "doctorate",
    "DC": "doctorate",
    "DVM": "doctorate",
    "PsyD": "doctorate",
    "PhD": "doctorate",
    "AuD": "doctorate",
    # Master's
    "MHA": "master",
    "MPH": "master",
    "MSN": "master",
    "PA": "master",
    "MSW": "master",
    "MS_SLP": "master",
    "MBA": "master",
    "MEd": "master",
    "MFA": "master",
    # Bachelor's
    "BSN": "bachelor",
    # Associate
    "ADN": "associate",
    # Doctoral (non-healthcare)
    "JD": "doctorate",
    "EdD": "doctorate",
    # Certificate / licensure (vocational-level)
    # Certificate / licensure (vocational-level)
    "RN": "certificate",
    "CNA": "certificate",
    "LPN": "certificate",
    "MA": "certificate",
    "CPhT": "certificate",
    "EMT": "certificate",
    "SurgTech": "certificate",
    # Generic degree levels (used as-is by LLM output and older records)
    "Bachelor": "bachelor",
    "Master": "master",
    "Doctorate": "doctorate",
    "Associate": "associate",
    "Certificate": "certificate",
    "Vocational": "certificate",
    "High School": "high_school",
}

# ---------------------------------------------------------------------------
# Alias table: normalized free text -> canonical code
#
# Keys are produced by _key() (lowercase, non-alphanumeric stripped).  Every
# label in frontend/lib/constants/credentials.ts, frontend CREDENTIAL_OPTIONS,
# the ingestion CREDENTIAL_KEYWORDS codes, and the LLM prompt vocabulary must
# be covered here.
# ---------------------------------------------------------------------------

_ALIASES: Dict[str, str] = {
    # --- Doctoral ---
    "pharmd": "PharmD",
    "doctorofpharmacy": "PharmD",
    "doctorofpharmacypharmd": "PharmD",
    "md": "MD",
    "doctorofmedicine": "MD",
    "doctorofmedicinemd": "MD",
    "medicaldoctor": "MD",
    "do": "DO",
    "doctorofosteopathicmedicine": "DO",
    "doctorofosteopathicmedicinedo": "DO",
    "osteopathicmedicine": "DO",
    "dpt": "DPT",
    "doctorofphysicaltherapy": "DPT",
    "doctorofphysicaltherapydpt": "DPT",
    "dnp": "DNP",
    "doctorofnursingpractice": "DNP",
    "doctorofnursingpracticednp": "DNP",
    "dds": "DDS_DMD",
    "dmd": "DDS_DMD",
    "ddsdmd": "DDS_DMD",
    "doctorofdentalsurgery": "DDS_DMD",
    "doctorofdentalmedicine": "DDS_DMD",
    "doctorofdentalsurgerymedicineddsdmd": "DDS_DMD",
    "dentistry": "DDS_DMD",
    "otd": "OTD",
    "doctorofoccupationaltherapy": "OTD",
    "doctorofoccupationaltherapyotd": "OTD",
    "od": "OD",
    "doctorofoptometry": "OD",
    "doctorofoptometryod": "OD",
    "optometry": "OD",
    "dpm": "DPM",
    "doctorofpodiatricmedicine": "DPM",
    "doctorofpodiatricmedicinedpm": "DPM",
    "podiatry": "DPM",
    "dc": "DC",
    "doctorofchiropractic": "DC",
    "doctorofchiropracticdc": "DC",
    "dvm": "DVM",
    "doctorofveterinarymedicine": "DVM",
    "doctorofveterinarymedicinedvm": "DVM",
    "veterinarymedicine": "DVM",
    "psyd": "PsyD",
    "doctorofpsychology": "PsyD",
    "doctorofpsychologypsyd": "PsyD",
    "phd": "PhD",
    "drph": "PhD",
    "phddrph": "PhD",
    "phddrphinhealthsciences": "PhD",
    "doctorofphilosophy": "PhD",
    "aud": "AuD",
    "audiology": "AuD",
    "audiologyaud": "AuD",
    "doctorofaudiology": "AuD",
    # --- Doctoral (non-healthcare) ---
    "jd": "JD",
    "jurisdoctor": "JD",
    "lawschool": "JD",
    "edd": "EdD",
    "doctorofeducation": "EdD",
    # --- Master's ---
    "mha": "MHA",
    "masterofhealthadministration": "MHA",
    "masterofhealthadministrationmha": "MHA",
    "healthadministration": "MHA",
    "mph": "MPH",
    "masterofpublichealth": "MPH",
    "masterofpublichealthmph": "MPH",
    "msn": "MSN",
    "masterofscienceinnursing": "MSN",
    "masterofscienceinnursingmsn": "MSN",
    "nursepractitioner": "MSN",
    "nursepractitionermsnfnpagnp": "MSN",
    "fnp": "MSN",
    "agnp": "MSN",
    "crna": "MSN",
    "nurseanesthesia": "MSN",
    "nurseanesthesiacrna": "MSN",
    "cnm": "MSN",
    "nursemidwifery": "MSN",
    "nursemidwiferycnm": "MSN",
    "pa": "PA",
    "mpas": "PA",
    "mspa": "PA",
    "physicianassistant": "PA",
    "physicianassistantstudiesmpasmspa": "PA",
    "msw": "MSW",
    "masterofsocialwork": "MSW",
    "masterofsocialworkmsw": "MSW",
    "clinicalsocialwork": "MSW",
    "clinicalsocialworkmswlcsw": "MSW",
    "lcsw": "MSW",
    "slp": "MS_SLP",
    "msslp": "MS_SLP",
    "speechlanguagepathology": "MS_SLP",
    "speechlanguagepathologymsslp": "MS_SLP",
    "mba": "MBA",
    "masterofbusinessadministration": "MBA",
    "med": "MEd",
    "masterofeducation": "MEd",
    "mfa": "MFA",
    "masteroffinearts": "MFA",
    # --- Bachelor's ---
    "bsn": "BSN",
    "bachelorofscienceinnursing": "BSN",
    "bachelorofscienceinnursingbsn": "BSN",
    "bachelorofnursing": "BSN",
    # --- Associate ---
    "adn": "ADN",
    "associatedegreeinnursing": "ADN",
    "associatedegreeinnursingadn": "ADN",
    "associateofscienceinnursing": "ADN",
    # --- Certificate / licensure ---
    "rn": "RN",
    "registerednurse": "RN",
    "cna": "CNA",
    "certifiednursingassistant": "CNA",
    "cnacertifiednursingassistant": "CNA",
    "lpn": "LPN",
    "lvn": "LPN",
    "lpnlvn": "LPN",
    "licensedpracticalnurse": "LPN",
    "licensedvocationalnurse": "LPN",
    "lpnlvnlicensedpracticalnurse": "LPN",
    "medicalassistant": "MA",
    "medicalassistantcertificate": "MA",
    "cpht": "CPhT",
    "certifiedpharmacytechnician": "CPhT",
    "pharmacytechnician": "CPhT",
    "pharmacytechniciancertificate": "CPhT",
    "emt": "EMT",
    "paramedic": "EMT",
    "emtparamedic": "EMT",
    "emtparamediccertificate": "EMT",
    "emergencymedicaltechnician": "EMT",
    "surgtech": "SurgTech",
    "surgicaltechnology": "SurgTech",
    "surgicaltechnologyst": "SurgTech",
    "surgicaltechnologist": "SurgTech",
    "surgicaltechnologycertificate": "SurgTech",
    # --- Bachelor's-degree tracks (CREDENTIALS_BY_LEVEL['undergraduate']) ---
    # These are field-of-study tracks pursued at the bachelor level.
    "biologypremed": "Bachelor",
    "chemistrybiochemistry": "Bachelor",
    "exercisesciencekinesiology": "Bachelor",
    "healthsciencespublichealth": "Bachelor",
    # --- Generic degree levels (LLM vocabulary / legacy CREDENTIAL_OPTIONS) ---
    "certificate": "Certificate",
    "diploma": "Certificate",
    "certificatediploma": "Certificate",
    "associate": "Associate",
    "associatedegree": "Associate",
    "associatedegreeasaasadn": "Associate",
    "aas": "Associate",
    "bachelor": "Bachelor",
    "bachelors": "Bachelor",
    "bachelordegree": "Bachelor",
    "bachelorsdegree": "Bachelor",
    "bachelorsdegreebsbabsn": "Bachelor",
    "bachelorofscience": "Bachelor",
    "bachelorofarts": "Bachelor",
    "bs": "Bachelor",
    "ba": "Bachelor",
    "bsba": "Bachelor",
    "master": "Master",
    "masters": "Master",
    "masterdegree": "Master",
    "mastersdegree": "Master",
    "mastersdegreemsmsnmpasmphmhmsw": "Master",
    "masterofscience": "Master",
    "masterofarts": "Master",
    "ms": "Master",
    "doctorate": "Doctorate",
    "doctoral": "Doctorate",
    "doctoraldegree": "Doctorate",
    "professionaldegree": "Doctorate",
    # full CREDENTIAL_OPTIONS doctoral label
    "doctoralprofessionalpracticepharmdmddoddsmddnpdptotdaudpmdvmpsydphddrph": "Doctorate",
    "highschool": "High School",
    "highschooldiploma": "High School",
    "hs": "High School",
    "ged": "High School",
    "vocational": "Vocational",
    "vocationaltechnical": "Vocational",
    "tradeschool": "Vocational",
    "trade": "Vocational",
}


def _key(value: str) -> str:
    """Normalize a credential string for alias lookup.

    'Pharm.D.' -> 'pharmd'; 'Doctor of Pharmacy (PharmD)' -> 'doctorofpharmacypharmd'.
    """
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def normalize_credential(value: str) -> Optional[str]:
    """Return the canonical credential code for a free-form value, or None.

    None means "unrecognized" — callers must not guess a code.  Canonical codes
    (e.g. 'PharmD') also normalize to themselves.
    """
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text in _LEVELS:
        return text
    canon = _ALIASES.get(_key(text))
    if canon is not None:
        return canon
    # Labels like "Some Program (PharmD)" — trust the parenthetical code when
    # it is a known credential abbreviation.
    m = re.search(r"\(([^)]+)\)", text)
    if m:
        for part in re.split(r"[/,;]", m.group(1)):
            canon = _ALIASES.get(_key(part))
            if canon is not None:
                return canon
    return None


def credential_tokens(value: str) -> Set[str]:
    """Return the lowercase match-token set for a *profile* credential.

    Named codes expand to {code, degree_level} so a PharmD candidate satisfies
    a generic "Doctorate" requirement; unrecognized strings produce
    {normalized_text} so identical free-text values still match.
    """
    canon = normalize_credential(value)
    if canon is None:
        raw = re.sub(r"\s+", " ", (value or "").strip().lower())
        return {raw} if raw else set()
    tokens = {canon.lower()}
    level = _LEVELS.get(canon)
    if level:
        tokens.add(level)
    return tokens


def credential_requirement_tokens(value: str) -> Set[str]:
    """Return the lowercase requirement-token set for a *scholarship* entry.

    Only the canonical code itself (never its degree level) — a "DDS"
    requirement must not accept a PharmD candidate just because both are
    doctorates. Generic level codes ("Doctorate", "Bachelor") carry their
    own name, which coincides with the level token on the profile side.
    """
    canon = normalize_credential(value)
    if canon is None:
        raw = re.sub(r"\s+", " ", (value or "").strip().lower())
        return {raw} if raw else set()
    return {canon.lower()}


def credential_token_set(values) -> Set[str]:
    """Union of credential_tokens over an iterable of raw profile values."""
    tokens: Set[str] = set()
    for v in values or []:
        tokens |= credential_tokens(str(v))
    return tokens


def credential_requirement_set(values) -> Set[str]:
    """Union of credential_requirement_tokens over scholarship values."""
    tokens: Set[str] = set()
    for v in values or []:
        tokens |= credential_requirement_tokens(str(v))
    return tokens
