"""LLM fallback extractor for unstructured scholarship pages.

Uses OpenAI gpt-4o-mini via `instructor` for structured JSON output.
Falls back to LiteLLM if `OPENAI_API_KEY` is absent but `LITELLM_MODEL`
is configured (e.g. Anthropic, Groq, etc.).

Triggered by the runner only when:
  a) The deterministic parser fails to extract critical fields
     (title, award_amount, or deadline missing/unparseable), or
  b) A novel unstructured page is ingested (no deterministic parser match).
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from .schema import ScholarshipExtract
from .utils.normalize import clean_text, map_credentials, map_disciplines

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured output schema (instructor / function-calling)
# ---------------------------------------------------------------------------

from pydantic import BaseModel, Field


class LLMScholarship(BaseModel):
    """Structured contract the LLM must return."""

    title: str = Field(..., description="Official scholarship title")
    provider: str = Field(..., description="Awarding organization or foundation")
    portal_url: str = Field(
        "",
        description=(
            "The exact, fully qualified HTTP/HTTPS application or portal URL "
            "(e.g. SmarterSelect, OpenWater, Formstack, or direct apply page). "
            "If no explicit apply button or link is found in the page text, "
            "default to the source URL provided above rather than guessing or "
            "constructing a link."
        ),
    )
    award_amount: int = Field(..., description="Award amount in whole US dollars")
    deadline: str = Field(..., description="Application deadline as YYYY-MM-DD")
    eligible_disciplines: List[str] = Field(
        default_factory=list,
        description=(
            "One or more of: pharmacy, medicine, nursing, therapeutics_rehab, "
            "diagnostic_imaging, public_health_emergency"
        ),
    )
    eligible_credentials: List[str] = Field(
        default_factory=list,
        description="e.g. ['BSN', 'PharmD', 'DPT', 'MD']",
    )
    min_gpa: Optional[float] = Field(None, description="Minimum GPA, or null")
    max_sai: Optional[int] = Field(None, description="Maximum SAI (Student Aid Index), or null")
    state_restrictions: List[str] = Field(
        default_factory=list,
        description="Two-letter state codes the award is restricted to, or empty",
    )
    required_affiliations: List[str] = Field(
        default_factory=list,
        description="Required professional memberships/affiliations, or empty",
    )
    matching_tags: List[str] = Field(
        default_factory=list,
        description="Short topical tags useful for matching, or empty",
    )
    metro_restrictions: List[str] = Field(
        default_factory=list,
        description=(
            "Target MSA name (e.g. 'New York-Newark-Jersey City') or CBSA code "
            "(e.g. 'cbsa:35620') if restricted to a specific metropolitan area. "
            "Empty if no metro-level restriction."
        ),
    )
    provider_type: Optional[str] = Field(
        None,
        description=(
            "Type of sponsoring organization, e.g. 'community_foundation', "
            "'hospital_system', 'national_association', 'state_agency', "
            "'corporate', 'faith_based', 'local_business', 'academic_department'. "
            "Null if not determinable."
        ),
    )
    provider_mission: Optional[str] = Field(
        None,
        description=(
            "Brief summary of the sponsoring organization's mission statement "
            "or purpose, if available on the page. Null if not found."
        ),
    )
    provider_core_values: List[str] = Field(
        default_factory=list,
        description=(
            "Core values or guiding principles of the sponsoring organization "
            "(e.g. ['equity', 'service', 'compassion']). Empty if not found."
        ),
    )
    is_local: bool = Field(
        False,
        description=(
            "True if the scholarship is specifically local to a city, county, "
            "parish, or university community (not a national award). "
            "False if national or if locality is unclear."
        ),
    )
    target_community: Optional[str] = Field(
        None,
        description=(
            "The specific municipality, county, parish, or university name "
            "the award is local to (e.g. 'Cleveland, OH', 'Cuyahoga County', "
            "'University of Michigan'). Null if not local or not specified."
        ),
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a scholarship extraction engine for GrantRx, a clinical education "
    "scholarship platform. Extract structured scholarship data from the provided "
    "webpage text. Be precise about:\n"
    "- Deadline: return as YYYY-MM-DD. If the page says 'annual' or gives a recurring "
    "  date without a year, use the next upcoming occurrence.\n"
    "- Award amount: whole US dollars. If a range is given, use the maximum. "
    "  If it says 'varies' with no number, return 0.\n"
    "- Min GPA: extract the numeric minimum (e.g. 3.0, 3.5). Null if not specified.\n"
    "- State restrictions: two-letter codes only (e.g. CA, NY, TX). Empty if none.\n"
    "- Metro restrictions: If the scholarship restricts eligibility to a specific "
    "  metropolitan area or group of counties, specify the matching Top 20 Metro "
    "  name (e.g. 'New York-Newark-Jersey City', 'Los Angeles-Long Beach-Anaheim') "
    "  or CBSA code (e.g. 'cbsa:35620'). Empty if no metro-level restriction.\n"
    "- Portal URL: Extract the exact, fully qualified HTTP/HTTPS application or "
    "  portal URL (e.g. SmarterSelect, OpenWater, Formstack, or direct apply page). "
    "  If no explicit apply button or link is found in the page text, default "
    "  directly to the source's exact input URL rather than guessing or "
    "  constructing a link.\n"
    "- Provider type: Classify the sponsoring organization type (e.g. "
    "  'community_foundation', 'hospital_system', 'national_association', "
    "  'state_agency', 'corporate', 'faith_based', 'local_business', "
    "  'academic_department'). Null if not determinable.\n"
    "- Provider mission: If the page includes a mission statement or purpose "
    "  for the sponsoring organization, summarize it briefly. Null if not found.\n"
    "- Provider core values: Extract any stated core values or guiding principles "
    "  of the organization (e.g. 'equity', 'service', 'compassion'). Empty if none.\n"
    "- Is local: Set to true if the award is specifically targeted at residents "
    "  of a particular city, county, parish, or university community. Set to false "
    "  for national awards or when locality is unclear.\n"
    "- Target community: If is_local is true, specify the municipality, county, "
    "  parish, or university name (e.g. 'Cleveland, OH', 'Cuyahoga County', "
    "  'University of Michigan'). Null if not local or not specified.\n"
    "Only include disciplines from this controlled vocabulary: "
    "pharmacy, medicine, nursing, therapeutics_rehab, diagnostic_imaging, "
    "public_health_emergency. If a field is not present, return null or an empty "
    "list as appropriate. Do not invent values."
)

USER_PROMPT_TEMPLATE = (
    "Source URL: {url}\n\n"
    "Webpage text (truncated):\n---\n{content}\n---\n\n"
    "Extract the scholarship fields as JSON."
)

VALID_DISCIPLINES = {
    "pharmacy",
    "medicine",
    "nursing",
    "therapeutics_rehab",
    "diagnostic_imaging",
    "public_health_emergency",
}


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


def _build_client():
    """Build an instructor-wrapped client.

    Order of preference:
    1. OpenAI (gpt-4o-mini) when OPENAI_API_KEY is set.
    2. LiteLLM when LITELLM_MODEL is set (e.g. 'anthropic/claude-3-5-sonnet').
    Returns (client, model_name) or raises RuntimeError.
    """
    import instructor

    openai_key = os.getenv("OPENAI_API_KEY")
    litellm_model = os.getenv("LITELLM_MODEL")

    if openai_key:
        from openai import AsyncOpenAI

        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        return instructor.from_openai(AsyncOpenAI(api_key=openai_key)), model

    if litellm_model:
        try:
            import litellm  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("LITELLM_MODEL set but litellm not installed") from exc
        # instructor supports LiteLLM via the OpenAI-compatible transport
        from openai import AsyncOpenAI

        base_url = os.getenv("LITELLM_BASE_URL")
        api_key = os.getenv("LITELLM_API_KEY", "dummy")
        client = instructor.from_openai(
            AsyncOpenAI(api_key=api_key, base_url=base_url) if base_url else AsyncOpenAI(api_key=api_key),
        )
        return client, litellm_model

    raise RuntimeError(
        "No LLM backend configured. Set OPENAI_API_KEY (gpt-4o-mini) or "
        "LITELLM_MODEL + LITELLM_API_KEY for the fallback parser."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _truncate(text: str, max_chars: int = 12000) -> str:
    text = clean_text(text)
    return text[:max_chars] if len(text) > max_chars else text


def _sanitize_disciplines(values: List[str]) -> List[str]:
    out = []
    for v in values:
        v = (v or "").strip().lower().replace("-", "_").replace(" ", "_")
        if v in VALID_DISCIPLINES and v not in out:
            out.append(v)
    return out


async def extract_with_llm(html: str, url: str) -> Optional[ScholarshipExtract]:
    """Run the LLM fallback parser. Returns None on failure."""
    try:
        client, model = _build_client()
    except RuntimeError as exc:
        logger.error("LLM fallback unavailable: %s", exc)
        return None

    # Strip HTML tags for the prompt payload
    try:
        from bs4 import BeautifulSoup

        content = clean_text(BeautifulSoup(html, "html.parser").get_text(separator=" "))
    except Exception:  # noqa: BLE001
        content = clean_text(html)

    content = _truncate(content)
    if not content:
        logger.warning("LLM fallback skipped: no extractable text for %s", url)
        return None

    user_prompt = USER_PROMPT_TEMPLATE.format(url=url, content=content)

    try:
        result = await client.chat.completions.create(
            model=model,
            response_model=LLMScholarship,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=900,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("LLM extraction failed for %s: %s", url, exc)
        return None

    disciplines = _sanitize_disciplines(result.eligible_disciplines)
    if not disciplines:
        # Best-effort keyword mapping from the raw content as a safety net
        disciplines = map_disciplines(content)

    credentials = result.eligible_credentials or map_credentials(content)

    # Use the LLM-extracted portal URL if provided, otherwise fall back to the source URL
    portal_url = result.portal_url.strip() if result.portal_url else ""
    if not portal_url:
        portal_url = url

    return ScholarshipExtract(
        title=result.title,
        provider=result.provider,
        portal_url=portal_url,
        award_amount=result.award_amount,
        deadline=result.deadline,
        eligible_disciplines=disciplines,
        eligible_credentials=credentials,
        min_gpa=result.min_gpa,
        max_sai=result.max_sai,
        state_restrictions=[s.upper() for s in result.state_restrictions if s],
        metro_restrictions=result.metro_restrictions or [],
        required_affiliations=result.required_affiliations,
        matching_tags=result.matching_tags,
        source="llm",
        provider_type=result.provider_type,
        provider_mission=result.provider_mission,
        provider_core_values=result.provider_core_values or [],
        is_local=result.is_local,
        target_community=result.target_community,
    )
