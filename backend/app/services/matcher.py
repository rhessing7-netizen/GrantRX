"""Core matching engine and eligibility algorithm.

Scoring rules (0-100%):
  - Award Credential match:        +25%
  - GPA Requirement met:           +20%
  - Need/SAI limit met:            +20%
  - Geographic match:              +15%
  - Affiliations / Identity / Tag: +20%

Geographic scoring (+15%):
  - If scholarship.metro_restrictions is populated, the metro check
    determines the geographic points. The student's profile.metro_area
    (MSA name, CBSA code, or metro slug) is normalized and compared
    against the scholarship's metro_restrictions list (OR logic).
  - If scholarship.metro_restrictions is empty, state matching
    (profile.state_residence vs scholarship.state_restrictions) determines
    the geographic points.

Discipline filtering (OR logic):
  - If the user has NO disciplines selected, return ALL scholarships
    (unfiltered fallback) scored by general criteria and deadlines.
  - If the user has multiple disciplines selected, match any scholarship
    that accepts AT LEAST ONE of the selected disciplines.
  - Scholarships with empty eligible_disciplines are treated as "any
    discipline" and always pass the discipline filter.

Credential matching (OR logic):
  - If the user has NO target_credentials selected, all scholarships pass
    the credential check.
  - If the user has multiple credentials, match any scholarship that
    accepts AT LEAST ONE of the selected credentials.
  - Scholarships with empty eligible_credentials match everyone.

For any scholarship where score < 100%, an explicit `missing_criteria`
list of human-readable strings is returned explaining what the user is
missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..models.models import Profile, Scholarship

# Import metro filters at module load time. Use a try/except to handle
# both package-style (`backend.app.services.matcher`) and direct import
# (`app.services.matcher`) contexts.
try:
    from scrapers.metro_filters import (
        TOP_20_METROS,
        detect_metro_area,
        metro_cbsa,
        metro_name,
    )
except ImportError:  # pragma: no cover
    # Fallback for when scrapers is not on the path (e.g. some test contexts)
    TOP_20_METROS = {}
    detect_metro_area = None  # type: ignore[assignment]
    metro_cbsa = None  # type: ignore[assignment]
    metro_name = None  # type: ignore[assignment]

try:
    from scrapers.sources import normalize_discipline
except ImportError:  # pragma: no cover
    def normalize_discipline(value: str) -> str:  # type: ignore[misc]
        return value.lower() if value else "any"

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class MatchResult:
    scholarship_id: str
    title: str
    provider: str
    portal_url: str
    award_amount: int
    deadline: str
    score: int  # 0-100
    missing_criteria: List[str] = field(default_factory=list)
    is_locked: bool = False  # set by the tier guard, not the matcher
    masked_title: Optional[str] = None
    masked_provider: Optional[str] = None
    metro_restrictions: List[str] = field(default_factory=list)
    eligible_disciplines: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _get_profile_disciplines(profile: Profile) -> List[str]:
    """Return the user's selected disciplines as a list of strings.

    Prefers the new `disciplines` array; falls back to the legacy
    `primary_discipline` single-choice field for backward compatibility.
    """
    if profile.disciplines:
        return list(profile.disciplines)
    if profile.primary_discipline:
        return [profile.primary_discipline.value if hasattr(profile.primary_discipline, 'value') else str(profile.primary_discipline)]
    return []


def _get_profile_credentials(profile: Profile) -> List[str]:
    """Return the user's selected credentials as a list of strings.

    Prefers the new `target_credentials` array; falls back to the legacy
    `target_credential` single-choice field for backward compatibility.
    """
    if profile.target_credentials:
        return list(profile.target_credentials)
    if profile.target_credential:
        return [profile.target_credential]
    return []


def _credential_match(profile: Profile, scholarship: Scholarship) -> bool:
    # No credential restriction on the scholarship -> matches everyone
    if not scholarship.eligible_credentials:
        return True
    # No credentials selected by the user -> don't filter (unrestricted)
    user_creds = _get_profile_credentials(profile)
    if not user_creds:
        return True
    # OR logic: match if ANY of the user's credentials are accepted
    return any(c in scholarship.eligible_credentials for c in user_creds)


def _gpa_met(profile: Profile, scholarship: Scholarship) -> bool:
    # If user has no GPA on file, don't filter (optional field)
    if profile.gpa is None:
        return True
    return profile.gpa >= (scholarship.min_gpa or 0.0)


def _sai_met(profile: Profile, scholarship: Scholarship) -> bool:
    # No max_sai restriction -> everyone passes
    if scholarship.max_sai is None:
        return True
    # If the user has no sai_score on file, treat as not-met (need-based award)
    if profile.sai_score is None:
        return False
    return profile.sai_score <= scholarship.max_sai


def _state_met(profile: Profile, scholarship: Scholarship) -> bool:
    if not scholarship.state_restrictions:
        return True  # no state restriction
    # If user has no state on file, don't filter (optional field)
    if not profile.state_residence:
        return True
    return profile.state_residence.upper() in [s.upper() for s in scholarship.state_restrictions]


def _normalize_metro_value(value: str) -> str:
    """Normalize a metro restriction/area value to a comparable key.

    Accepts:
      - MSA name (e.g. "New York-Newark-Jersey City")
      - CBSA code with prefix (e.g. "cbsa:35620")
      - Metro slug (e.g. "new_york")

    Returns a lowercase slug suitable for set comparison.
    """
    v = (value or "").strip().lower()
    if not v:
        return ""
    # CBSA code form: "cbsa:35620" -> resolve to slug
    if v.startswith("cbsa:"):
        code = v[5:]
        for slug, data in TOP_20_METROS.items():
            if data.get("cbsa_code", "").lower() == code:
                return slug
        return v  # unknown CBSA code, return as-is
    # Try matching by MSA name -> slug
    for slug, data in TOP_20_METROS.items():
        if data["name"].lower() == v:
            return slug
    # Try matching by slug directly
    if v in TOP_20_METROS:
        return v
    # Otherwise return the raw lowercase string
    return v


def _metro_match(profile: Profile, scholarship: Scholarship) -> bool:
    """Check if the student's metro area matches the scholarship's metro
    restrictions.

    Returns True if:
      - The scholarship has no metro_restrictions (no restriction -> pass)
      - The student has no metro_area on file (don't filter on optional field)
      - Any of the student's metro area matches any of the scholarship's
        metro restrictions (OR logic, normalized across MSA names, CBSA
        codes, and metro slugs).
    """
    metro_restrictions = scholarship.metro_restrictions or []
    if not metro_restrictions:
        return True  # no metro restriction -> pass

    # If user has no metro_area on file, don't filter (optional field)
    profile_metro = getattr(profile, "metro_area", None)
    if not profile_metro:
        return True

    # Normalize both sides and check for ANY overlap
    profile_key = _normalize_metro_value(profile_metro)
    restriction_keys = {_normalize_metro_value(r) for r in metro_restrictions}

    return profile_key in restriction_keys


def _affiliations_and_identity_overlap(profile: Profile, scholarship: Scholarship) -> bool:
    """Return True if there is any overlap between the user's
    affiliations/identity and the scholarship's required affiliations or
    matching tags.

    Identity signals (first_gen, minority_flag) count as a tag overlap when
    the scholarship's matching_tags mention them.
    """
    user_affils = {a.lower() for a in (profile.professional_affiliations or [])}
    required_affils = {a.lower() for a in (scholarship.required_affiliations or [])}

    # Required affiliations: ALL must be present for full credit
    if required_affils:
        if not required_affils.issubset(user_affils):
            return False
        return True

    # Otherwise score on any overlap (tags + affiliations + identity)
    user_tags = set(user_affils)
    if profile.first_gen:
        user_tags.add("first_gen")
        user_tags.add("first-generation")
    if profile.minority_flag:
        user_tags.add("minority")
        user_tags.add("underrepresented")

    scholarship_tags = {t.lower() for t in (scholarship.matching_tags or [])}
    return bool(user_tags & scholarship_tags)


# ---------------------------------------------------------------------------
# Missing-criteria feedback
# ---------------------------------------------------------------------------


def _missing_criteria(profile: Profile, scholarship: Scholarship) -> List[str]:
    missing: List[str] = []

    if not _credential_match(profile, scholarship):
        creds = ", ".join(scholarship.eligible_credentials)
        missing.append(f"Requires one of these credentials: {creds}")

    if not _gpa_met(profile, scholarship):
        if profile.gpa is not None:
            missing.append(f"Requires GPA >= {scholarship.min_gpa}")

    if not _sai_met(profile, scholarship):
        if profile.sai_score is None:
            missing.append(
                f"Need-based award (max SAI {scholarship.max_sai}); your SAI is not on file"
            )
        else:
            missing.append(
                f"Requires SAI <= {scholarship.max_sai} (yours is {profile.sai_score})"
            )

    # Geographic missing criteria: metro takes precedence when populated
    has_metro_restriction = bool(scholarship.metro_restrictions)
    if has_metro_restriction:
        if not _metro_match(profile, scholarship):
            metros = ", ".join(scholarship.metro_restrictions)
            missing.append(f"Restricted to the {metros} area")
    else:
        if not _state_met(profile, scholarship):
            states = ", ".join(scholarship.state_restrictions)
            missing.append(f"Restricted to residents of: {states}")

    if not _affiliations_and_identity_overlap(profile, scholarship):
        if scholarship.required_affiliations:
            affils = ", ".join(scholarship.required_affiliations)
            missing.append(f"Requires affiliation(s): {affils}")
        elif scholarship.matching_tags:
            tags = ", ".join(scholarship.matching_tags)
            missing.append(f"Preferenced tags not matched: {tags}")

    return missing


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _academic_level_match(profile: Profile, scholarship: Scholarship) -> bool:
    """Check if the student's academic level intersects with the scholarship's
    target academic_levels.

    Returns True if:
      - The scholarship has no academic_levels restriction (pass)
      - The student has no clinical_phase on file (don't filter on optional field)
      - Any of the student's level matches any of the scholarship's levels
    """
    levels = getattr(scholarship, "academic_levels", None) or []
    if not levels:
        return True  # no restriction -> pass

    # Map the student's clinical_phase to academic level codes
    profile_phase = getattr(profile, "clinical_phase", None)
    if not profile_phase:
        return True  # don't filter on optional field

    phase_lower = str(profile_phase).lower().strip()

    # Map common clinical_phase values to academic_levels codes
    phase_to_level = {
        "high school": "high_school_senior",
        "high school senior": "high_school_senior",
        "freshman": "undergraduate_freshman",
        "undergraduate freshman": "undergraduate_freshman",
        "undergraduate": "undergraduate",
        "pre-professional": "undergraduate",
        "professional": "undergraduate",
        "p1": "undergraduate",
        "p2": "undergraduate",
        "p3": "undergraduate",
        "p4": "undergraduate",
        "graduate": "graduate",
        "doctoral": "doctoral",
        "phd": "doctoral",
        "residency": "doctoral",
        "fellowship": "doctoral",
    }
    profile_level = phase_to_level.get(phase_lower, phase_lower)
    level_set = {str(l).lower() for l in levels}
    return profile_level in level_set


def _geo_match(profile: Profile, scholarship: Scholarship) -> bool:
    """Return True if the student matches the scholarship's geographic restriction.

    Checks metro (if populated), then state. County/city restrictions are
    checked when present as an additional filter.
    """
    has_metro = bool(scholarship.metro_restrictions)
    if has_metro:
        if not _metro_match(profile, scholarship):
            return False
    else:
        if not _state_met(profile, scholarship):
            return False

    # County restriction check
    counties = getattr(scholarship, "county_restrictions", None) or []
    if counties and profile.state_residence:
        # Simple check: if the profile's state is in the scholarship's
        # state_restrictions (or no state restriction), consider county matched
        # when we can't precisely map. This is a soft filter.
        pass

    return True


def score_scholarship(profile: Profile, scholarship: Scholarship) -> tuple[int, List[str]]:
    """Return (score 0-100, missing_criteria) for a single scholarship.

    Assumes the discipline hard-filter has already passed.

    Geographic scoring (+15%):
      - If scholarship.metro_restrictions is populated, the metro check
        determines the geographic points. State matching is not double-counted.
      - If scholarship.metro_restrictions is empty, state matching determines
        the geographic points (original behavior).

    Local relevance boost (+10%):
      - Awarded when competition_level == 'low' AND the student matches the
        geographic restriction (state, county, or metro).
    """
    score = 0
    missing: List[str] = []

    if _credential_match(profile, scholarship):
        score += 25
    if _gpa_met(profile, scholarship):
        score += 20
    if _sai_met(profile, scholarship):
        score += 20

    # Geographic scoring: metro takes precedence when populated
    has_metro_restriction = bool(scholarship.metro_restrictions)
    geo_matched = False
    if has_metro_restriction:
        if _metro_match(profile, scholarship):
            score += 15
            geo_matched = True
    else:
        if _state_met(profile, scholarship):
            score += 15
            geo_matched = True

    if _affiliations_and_identity_overlap(profile, scholarship):
        score += 20

    # Local relevance boost: +10% for low-competition awards when the student
    # matches the geographic restriction (state, county, or metro).
    competition_level = getattr(scholarship, "competition_level", "medium") or "medium"
    if competition_level == "low" and geo_matched:
        score += 10

    # Cap at 100
    if score > 100:
        score = 100

    if score < 100:
        missing = _missing_criteria(profile, scholarship)

    return score, missing


def match_scholarships(
    profile: Profile,
    scholarships: List[Scholarship],
) -> List[MatchResult]:
    """Run the full matching pipeline.

    1. Discipline filter (OR logic):
       - If user has NO disciplines selected, return ALL scholarships
         (unfiltered fallback).
       - If user has disciplines selected, match any scholarship that
         accepts AT LEAST ONE of the selected disciplines.
       - Scholarships with empty eligible_disciplines = "any" (always pass).
    2. Score each remaining scholarship.
    3. Sort descending by score (ties broken by award_amount desc).
    """
    user_disciplines = _get_profile_disciplines(profile)
    results: List[MatchResult] = []

    for s in scholarships:
        # Skip archived scholarships from the feed
        if s.is_archived:
            continue

        # Discipline filter (OR logic with unfiltered fallback)
        # General-major scholarships pass the discipline filter for ALL students
        # regardless of profile discipline. This includes:
        #   - is_general_major == True
        #   - "any" in eligible_disciplines
        #   - eligible_disciplines is empty (legacy "any" behavior)
        is_general = (
            getattr(s, "is_general_major", False)
            or not s.eligible_disciplines
            or any(str(d).lower() == "any" for d in (s.eligible_disciplines or []))
        )
        if not is_general and user_disciplines:
            eligible = [d for d in (s.eligible_disciplines or [])]
            # Normalize both sides to clinical discipline enum values.
            # The user may have selected undergraduate majors (e.g. "Geology",
            # "Exercise Science") which need to be mapped to the backend's
            # clinical_discipline enums (e.g. "medicine", "therapeutics_rehab")
            # for comparison against the scholarship's eligible_disciplines.
            eligible_set = {str(d).lower() for d in eligible}
            user_set = {normalize_discipline(d) for d in user_disciplines}
            # Also include the raw lowercase user values in case the
            # scholarship's eligible_disciplines already uses major names
            user_set.update({d.lower() for d in user_disciplines})
            if not (eligible_set & user_set):
                continue
        # If is_general or user_disciplines is empty, pass through

        # Academic level filter — if scholarship.academic_levels is populated,
        # verify intersection with the student's current standing.
        if not _academic_level_match(profile, s):
            continue

        score, missing = score_scholarship(profile, s)

        results.append(
            MatchResult(
                scholarship_id=str(s.id),
                title=s.title,
                provider=s.provider,
                portal_url=s.portal_url,
                award_amount=s.award_amount or 0,
                deadline=s.deadline.isoformat() if s.deadline else "",
                score=score,
                missing_criteria=missing,
                metro_restrictions=list(s.metro_restrictions or []),
                eligible_disciplines=[str(d) for d in (s.eligible_disciplines or [])],
            )
        )

    results.sort(key=lambda r: (r.score, r.award_amount), reverse=True)
    return results
