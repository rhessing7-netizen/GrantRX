"""AI Statement Coach & 4-Part Essay Outliner.

Generates structured essay outlines tailored to a scholarship provider's
mission and core values. Uses OpenAI gpt-4o-mini via instructor for
structured JSON output, with LiteLLM fallback.

IMPORTANT GUARDRAIL: This service does NOT write completed essay prose.
It generates structured bullet points, estimated section word counts,
and coaching prompts only.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input / Output schemas
# ---------------------------------------------------------------------------


class EssayOutlineRequest(BaseModel):
    """Input schema for the essay outline generator."""

    scholarship_title: str
    provider: str
    prompt: str = ""
    word_limit: Optional[int] = 500
    provider_mission: Optional[str] = None
    provider_core_values: List[str] = []
    user_discipline: Optional[str] = None
    user_credential: Optional[str] = None
    lived_experience_notes: Optional[str] = None
    work_volunteer_experience: Optional[str] = None
    academic_topics_of_interest: Optional[str] = None


class EssayNarrativeSection(BaseModel):
    """One of the 4 narrative sections of the essay outline."""

    title: str = Field(..., description="Section heading")
    estimated_word_count: int = Field(
        ..., description="Suggested word count for this section"
    )
    talking_points: List[str] = Field(
        default_factory=list,
        description="Bullet-point talking points the student should cover",
    )
    coaching_tips: List[str] = Field(
        default_factory=list,
        description="Specific writing coaching tips for this section",
    )


class EssayOutlineResponse(BaseModel):
    """Structured 4-part essay outline returned to the student."""

    suggested_theme: str = Field(
        ..., description="A unifying theme or narrative arc for the essay"
    )
    mission_alignment_angle: str = Field(
        ...,
        description=(
            "How to explicitly weave the provider's mission and core values "
            "into the essay narrative"
        ),
    )
    part_1_personal_story: EssayNarrativeSection
    part_2_work_experience: EssayNarrativeSection
    part_3_academic_citation: EssayNarrativeSection
    part_4_future_service: EssayNarrativeSection
    checklist: List[str] = Field(
        default_factory=list,
        description="Pre-submission checklist items",
    )


# ---------------------------------------------------------------------------
# LLM structured output schema (instructor / function-calling)
# ---------------------------------------------------------------------------


class LLMEssayOutline(BaseModel):
    """Structured contract the LLM must return."""

    suggested_theme: str = Field(
        ..., description="A unifying theme or narrative arc for the essay"
    )
    mission_alignment_angle: str = Field(
        ...,
        description=(
            "How to explicitly weave the provider's mission and core values "
            "into the essay narrative"
        ),
    )
    part_1_personal_story: EssayNarrativeSection = Field(
        ...,
        description=(
            "Section 1: Personal Story & Upbringing — origin, family background, "
            "lived experiences that shaped the student's path"
        ),
    )
    part_2_work_experience: EssayNarrativeSection = Field(
        ...,
        description=(
            "Section 2: Work & Volunteer Track Record — clinical, shadowing, "
            "volunteer, or professional experiences demonstrating commitment"
        ),
    )
    part_3_academic_citation: EssayNarrativeSection = Field(
        ...,
        description=(
            "Section 3: Academic Foundation & Citations — coursework, research, "
            "topics of interest, and academic achievements with citation guidance"
        ),
    )
    part_4_future_service: EssayNarrativeSection = Field(
        ...,
        description=(
            "Section 4: Future Service & Community Impact — how the student will "
            "give back, aligned with the provider's mission"
        ),
    )
    checklist: List[str] = Field(
        default_factory=list,
        description="Pre-submission checklist items (e.g. proofread, check word count)",
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are an expert scholarship essay coach for GrantRx, a clinical education "
    "scholarship platform. Your job is to help healthcare students create "
    "compelling, authentic personal statements for scholarship applications.\n\n"
    "CRITICAL GUARDRAIL: Do NOT write the completed essay prose. Generate only:\n"
    "- Structured bullet-point talking points\n"
    "- Estimated section word counts\n"
    "- Coaching tips and writing prompts\n"
    "- A suggested unifying theme\n"
    "- Mission alignment guidance\n\n"
    "The outline must have exactly 4 narrative sections:\n"
    "1. Personal Story & Upbringing — origin, family, lived experiences\n"
    "2. Work & Volunteer Track Record — clinical, shadowing, community service\n"
    "3. Academic Foundation & Citations — coursework, research, topics of interest\n"
    "4. Future Service & Community Impact — how the student will give back\n\n"
    "Tailor every section to the scholarship provider's mission and core values. "
    "If the provider's mission is available, explicitly explain how to weave it "
    "into the narrative. Use the student's discipline, credential, and personal "
    "notes to make the outline specific and authentic.\n"
    "Distribute the word limit across the 4 sections proportionally. "
    "Each section should have 3-5 talking points and 2-3 coaching tips."
)

USER_PROMPT_TEMPLATE = (
    "Scholarship: {scholarship_title}\n"
    "Provider: {provider}\n"
    "Provider Mission: {provider_mission}\n"
    "Provider Core Values: {core_values}\n"
    "Essay Prompt/Topic: {prompt}\n"
    "Word Limit: {word_limit}\n\n"
    "Student Context:\n"
    "- Discipline: {discipline}\n"
    "- Credential: {credential}\n"
    "- Lived Experience Notes: {lived_experience}\n"
    "- Work/Volunteer Experience: {work_experience}\n"
    "- Academic Topics of Interest: {academic_topics}\n\n"
    "Generate a 4-part essay outline with talking points and coaching tips. "
    "Do NOT write essay prose — only structured guidance."
)


# ---------------------------------------------------------------------------
# Client construction (reuses the same pattern as llm_parser.py)
# ---------------------------------------------------------------------------


def _build_client():
    """Build an instructor-wrapped client.

    Order of preference:
    1. OpenAI (gpt-4o-mini) when OPENAI_API_KEY is set.
    2. LiteLLM when LITELLM_MODEL is set.
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
        from openai import AsyncOpenAI

        base_url = os.getenv("LITELLM_BASE_URL")
        api_key = os.getenv("LITELLM_API_KEY", "dummy")
        client = instructor.from_openai(
            AsyncOpenAI(api_key=api_key, base_url=base_url) if base_url else AsyncOpenAI(api_key=api_key),
        )
        return client, litellm_model

    raise RuntimeError(
        "No LLM backend configured. Set OPENAI_API_KEY (gpt-4o-mini) or "
        "LITELLM_MODEL + LITELLM_API_KEY for the essay outline generator."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_essay_outline(
    request: EssayOutlineRequest,
) -> Optional[EssayOutlineResponse]:
    """Generate a structured 4-part essay outline via the LLM.

    Returns None if no LLM backend is configured or the call fails.
    """
    try:
        client, model = _build_client()
    except RuntimeError as exc:
        logger.error("Essay outline LLM unavailable: %s", exc)
        return None

    user_prompt = USER_PROMPT_TEMPLATE.format(
        scholarship_title=request.scholarship_title,
        provider=request.provider,
        provider_mission=request.provider_mission or "Not specified",
        core_values=", ".join(request.provider_core_values) if request.provider_core_values else "Not specified",
        prompt=request.prompt or "General personal statement",
        word_limit=request.word_limit or 500,
        discipline=request.user_discipline or "Not specified",
        credential=request.user_credential or "Not specified",
        lived_experience=request.lived_experience_notes or "Not provided",
        work_experience=request.work_volunteer_experience or "Not provided",
        academic_topics=request.academic_topics_of_interest or "Not provided",
    )

    try:
        result = await client.chat.completions.create(
            model=model,
            response_model=LLMEssayOutline,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=2000,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Essay outline generation failed: %s", exc)
        return None

    return EssayOutlineResponse(
        suggested_theme=result.suggested_theme,
        mission_alignment_angle=result.mission_alignment_angle,
        part_1_personal_story=result.part_1_personal_story,
        part_2_work_experience=result.part_2_work_experience,
        part_3_academic_citation=result.part_3_academic_citation,
        part_4_future_service=result.part_4_future_service,
        checklist=result.checklist,
    )
