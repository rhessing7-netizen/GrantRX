"""Core matching engine and eligibility algorithm.

Hard gates (disqualify completely — no partial scoring):
  - Discipline gate: If scholarship.eligible_disciplines is populated and
    does NOT contain "any", the user's discipline(s) must intersect.
    Scholarships with empty eligible_disciplines or ["any"] pass everyone.
  - Credential gate: If scholarship.eligible_credentials is populated, the
    user's credential(s) must intersect. Scholarships with empty
    eligible_credentials pass everyone.
  - Academic level gate: If scholarship.academic_levels is populated, the
    student's current standing must intersect.

Soft attribute scoring (0-100%, four equal buckets of +25%):
  - GPA requirement met:           +25%
  - Geographic match (state/metro): +25%
  - Financial need / SAI met:      +25%
  - Affiliations / Identity / Tag: +25%

Local relevance boost (+10%, capped at 100):
  - Awarded when competition_level == 'low' AND the student matches the
    geographic restriction.

Geographic scoring (+25%):
  - If scholarship.metro_restrictions is populated, the metro check
    determines the geographic points. The student's profile.metro_area
    (MSA name, CBSA code, or metro slug) is normalized and compared
    against the scholarship's metro_restrictions list (OR logic).
  - If scholarship.metro_restrictions is empty, state matching
    (profile.state_residence vs scholarship.state_restrictions) determines
    the geographic points.

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
    # Employer / service-obligation informational fields (defaults keep
    # existing feed payloads backward-compatible).
    funding_type: str = "scholarship"
    employment_required: bool = False
    has_service_commitment: bool = False
    annual_benefit_cap: Optional[int] = None
    vendor_platform: Optional[str] = None
    # Optional detail fields populated for the preview drawer. Defaults
    # keep existing feed payloads backward-compatible.
    provider_mission: Optional[str] = None
    provider_core_values: List[str] = field(default_factory=list)
    eligible_credentials: List[str] = field(default_factory=list)
    min_gpa: Optional[float] = None
    max_sai: Optional[float] = None
    state_restrictions: List[str] = field(default_factory=list)
    is_general_major: bool = False
    # Per-bucket score composition (see score_breakdown). Empty dict for
    # payloads produced before this field existed.
    score_breakdown: dict[str, int] = field(default_factory=dict)


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


def is_discipline_eligible(profile: Profile, scholarship: Scholarship) -> bool:
    """Strict gate: Disqualify completely if disciplines or credentials do not match.

    Unrestricted grants (empty arrays or 'any') remain eligible for all.

    Returns False if:
      - scholarship.eligible_disciplines is populated, does NOT contain "any",
        and the user's discipline(s) do not intersect.
      - scholarship.eligible_credentials is populated and the user's
        credential(s) do not intersect (only when the user has credentials
        on file).

    Returns True otherwise (scholarship passes the hard gate).
    """
    # 1. Hard Discipline Check
    eligible_disciplines = scholarship.eligible_disciplines or []
    if eligible_disciplines:
        # Check if "any" is an allowed discipline (unrestricted)
        if not any(str(d).lower() == "any" for d in eligible_disciplines):
            user_disciplines = _get_profile_disciplines(profile)
            if user_disciplines:
                # Normalize both sides for comparison
                eligible_set = {str(d).lower() for d in eligible_disciplines}
                user_set = {normalize_discipline(d) for d in user_disciplines}
                user_set.update({d.lower() for d in user_disciplines})
                if not (eligible_set & user_set):
                    return False

    # 2. Hard Credential/Degree Track Check
    eligible_credentials = scholarship.eligible_credentials or []
    if eligible_credentials:
        user_credentials = _get_profile_credentials(profile)
        if user_credentials and not any(
            c in eligible_credentials for c in user_credentials
        ):
            return False

    return True


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
    """Return human-readable strings for unmet soft attributes.

    Discipline and credential mismatches are NOT included here because they
    are hard-gated by `is_discipline_eligible()` — scholarships that fail
    those gates are dropped entirely from the feed.
    """
    missing: List[str] = []

    if not _gpa_met(profile, scholarship):
        if profile.gpa is not None:
            missing.append(f"Requires GPA >= {scholarship.min_gpa}")

    if not _sai_met(profile, scholarship):
        if profile.sai_score is None:
            missing.append("Requires demonstrated financial need")
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


# Score bucket keys — stable identifiers surfaced to the frontend so the
# "Why am I seeing this?" breakdown reflects the real scoring weights.
BUCKET_GPA = "gpa"
BUCKET_GEO = "geo"
BUCKET_SAI = "sai"
BUCKET_AFFIL = "affiliations"
BUCKET_LOCAL = "local_boost"
BUCKET_WEIGHT = 25
LOCAL_BOOST_WEIGHT = 10


def score_breakdown(profile: Profile, scholarship: Scholarship) -> dict[str, int]:
    """Return the per-bucket score composition for a single scholarship.

    Keys are the BUCKET_* constants; values are the points actually awarded
    (0 or the bucket weight). Summing the values (capped at 100) yields the
    same number as :func:`score_scholarship`.
    """
    breakdown: dict[str, int] = {
        BUCKET_GPA: 0,
        BUCKET_GEO: 0,
        BUCKET_SAI: 0,
        BUCKET_AFFIL: 0,
        BUCKET_LOCAL: 0,
    }

    # Bucket 1: GPA (+25%)
    if _gpa_met(profile, scholarship):
        breakdown[BUCKET_GPA] = BUCKET_WEIGHT

    # Bucket 2: Geographic match (+25%)
    # Metro takes precedence when populated; otherwise state matching.
    has_metro_restriction = bool(scholarship.metro_restrictions)
    geo_matched = False
    if has_metro_restriction:
        if _metro_match(profile, scholarship):
            geo_matched = True
    else:
        if _state_met(profile, scholarship):
            geo_matched = True
    if geo_matched:
        breakdown[BUCKET_GEO] = BUCKET_WEIGHT

    # Bucket 3: Financial need / SAI (+25%)
    if _sai_met(profile, scholarship):
        breakdown[BUCKET_SAI] = BUCKET_WEIGHT

    # Bucket 4: Affiliations / Identity / Tags (+25%)
    if _affiliations_and_identity_overlap(profile, scholarship):
        breakdown[BUCKET_AFFIL] = BUCKET_WEIGHT

    # Local relevance boost: +10% for low-competition awards when the student
    # matches the geographic restriction (state, county, or metro).
    competition_level = getattr(scholarship, "competition_level", "medium") or "medium"
    if competition_level == "low" and geo_matched:
        breakdown[BUCKET_LOCAL] = LOCAL_BOOST_WEIGHT

    return breakdown


def score_scholarship(profile: Profile, scholarship: Scholarship) -> tuple[int, List[str]]:
    """Return (score 0-100, missing_criteria) for a single scholarship.

    Assumes the discipline and credential hard gates have already passed
    (via `is_discipline_eligible`).

    Soft attribute scoring (four equal buckets of +25%):
      - GPA requirement met:           +25%
      - Geographic match (state/metro): +25%
      - Financial need / SAI met:      +25%
      - Affiliations / Identity / Tag: +25%

    Local relevance boost (+10%, capped at 100):
      - Awarded when competition_level == 'low' AND the student matches the
        geographic restriction (state, county, or metro).
    """
    missing: List[str] = []

    # Cap at 100
    score = min(100, sum(score_breakdown(profile, scholarship).values()))

    if score < 100:
        missing = _missing_criteria(profile, scholarship)

    # Always surface informational notices for employer tuition assistance
    # and service-obligation programs, even on a perfect match. These do NOT
    # penalize the matching score — they help the student make an informed
    # decision about employer ties or post-graduation service obligations.
    if getattr(scholarship, "has_service_commitment", False):
        notice = "Includes post-graduation service commitment"
        if notice not in missing:
            missing.append(notice)
    if getattr(scholarship, "employment_required", False):
        notice = "Requires employment or clinical apprenticeship"
        if notice not in missing:
            missing.append(notice)

    return score, missing


def _opt_str(value) -> Optional[str]:
    """Coerce an optional text column to ``str`` (or ``None``)."""
    return value if isinstance(value, str) and value else None


def _opt_float(value) -> Optional[float]:
    """Coerce an optional numeric column to ``float`` (or ``None``)."""
    return float(value) if isinstance(value, (int, float)) and value else None


def _str_list(value) -> List[str]:
    """Coerce an optional array column to a ``List[str]``."""
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else []


def match_scholarships(
    profile: Profile,
    scholarships: List[Scholarship],
) -> List[MatchResult]:
    """Run the full matching pipeline.

    1. Hard gates (drop completely — no partial scoring):
       - Discipline gate via `is_discipline_eligible()`
       - Credential gate via `is_discipline_eligible()`
       - Academic level gate via `_academic_level_match()`
    2. Score each remaining scholarship on soft attributes (4x25%).
    3. Sort descending by score (ties broken by award_amount desc).
    """
    results: List[MatchResult] = []

    for s in scholarships:
        # Skip archived scholarships from the feed
        if s.is_archived:
            continue

        # Hard gate: discipline + credential strict check
        if not is_discipline_eligible(profile, s):
            continue

        # Academic level filter — if scholarship.academic_levels is populated,
        # verify intersection with the student's current standing.
        if not _academic_level_match(profile, s):
            continue

        score, missing = score_scholarship(profile, s)
        breakdown = score_breakdown(profile, s)

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
                funding_type=getattr(s, "funding_type", "scholarship") or "scholarship",
                employment_required=bool(getattr(s, "employment_required", False)),
                has_service_commitment=bool(getattr(s, "has_service_commitment", False)),
                annual_benefit_cap=getattr(s, "annual_benefit_cap", None),
                vendor_platform=getattr(s, "vendor_platform", None),
                provider_mission=_opt_str(getattr(s, "provider_mission", None)),
                provider_core_values=_str_list(getattr(s, "provider_core_values", None)),
                eligible_credentials=_str_list(s.eligible_credentials),
                min_gpa=_opt_float(s.min_gpa),
                max_sai=_opt_float(s.max_sai),
                state_restrictions=_str_list(s.state_restrictions),
                is_general_major=getattr(s, "is_general_major", False) is True,
                score_breakdown=breakdown,
            )
        )

    results.sort(key=lambda r: (r.score, r.award_amount), reverse=True)
    return results
