"""Unit tests for the AI Statement Coach & 4-Part Essay Outliner.

Tests verify:
- EssayOutlineRequest schema accepts all input fields
- EssayOutlineResponse schema has all 4 narrative sections
- EssayNarrativeSection has title, word count, talking points, coaching tips
- generate_essay_outline returns None when no LLM backend is configured
- generate_essay_outline returns a valid EssayOutlineResponse when LLM is mocked
- System prompt contains the "do NOT write essay prose" guardrail
- User prompt template includes provider mission and core values
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.outline_service import (
    EssayNarrativeSection,
    EssayOutlineRequest,
    EssayOutlineResponse,
    LLMEssayOutline,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    generate_essay_outline,
)


# ---------------------------------------------------------------------------
# Tests: EssayOutlineRequest schema
# ---------------------------------------------------------------------------


class TestEssayOutlineRequest:
    def test_required_fields(self):
        req = EssayOutlineRequest(
            scholarship_title="Test Scholarship",
            provider="Test Provider",
        )
        assert req.scholarship_title == "Test Scholarship"
        assert req.provider == "Test Provider"

    def test_defaults(self):
        req = EssayOutlineRequest(
            scholarship_title="Test",
            provider="Provider",
        )
        assert req.prompt == ""
        assert req.word_limit == 500
        assert req.provider_mission is None
        assert req.provider_core_values == []
        assert req.user_discipline is None
        assert req.user_credential is None
        assert req.lived_experience_notes is None
        assert req.work_volunteer_experience is None
        assert req.academic_topics_of_interest is None

    def test_all_fields_settable(self):
        req = EssayOutlineRequest(
            scholarship_title="Pharmacy Award",
            provider="APhA",
            prompt="Describe your commitment to pharmacy",
            word_limit=750,
            provider_mission="Advancing the pharmacy profession",
            provider_core_values=["equity", "service"],
            user_discipline="pharmacy",
            user_credential="PharmD",
            lived_experience_notes="First-gen student from rural Ohio",
            work_volunteer_experience="2 years at free clinic",
            academic_topics_of_interest="Pharmacogenomics",
        )
        assert req.word_limit == 750
        assert req.provider_core_values == ["equity", "service"]
        assert req.user_discipline == "pharmacy"


# ---------------------------------------------------------------------------
# Tests: EssayOutlineResponse schema
# ---------------------------------------------------------------------------


class TestEssayOutlineResponse:
    def test_has_four_narrative_sections(self):
        fields = EssayOutlineResponse.model_fields
        assert "part_1_personal_story" in fields
        assert "part_2_work_experience" in fields
        assert "part_3_academic_citation" in fields
        assert "part_4_future_service" in fields

    def test_has_suggested_theme(self):
        fields = EssayOutlineResponse.model_fields
        assert "suggested_theme" in fields

    def test_has_mission_alignment_angle(self):
        fields = EssayOutlineResponse.model_fields
        assert "mission_alignment_angle" in fields

    def test_has_checklist(self):
        fields = EssayOutlineResponse.model_fields
        assert "checklist" in fields

    def test_can_construct_full_response(self):
        section = EssayNarrativeSection(
            title="Personal Story",
            estimated_word_count=150,
            talking_points=["Origin", "Family"],
            coaching_tips=["Be specific"],
        )
        resp = EssayOutlineResponse(
            suggested_theme="From rural roots to pharmacy leader",
            mission_alignment_angle="Weave APhA's equity value into your origin story",
            part_1_personal_story=section,
            part_2_work_experience=section,
            part_3_academic_citation=section,
            part_4_future_service=section,
            checklist=["Proofread", "Check word count"],
        )
        assert resp.suggested_theme == "From rural roots to pharmacy leader"
        assert resp.checklist == ["Proofread", "Check word count"]
        assert resp.part_1_personal_story.estimated_word_count == 150


# ---------------------------------------------------------------------------
# Tests: EssayNarrativeSection schema
# ---------------------------------------------------------------------------


class TestEssayNarrativeSection:
    def test_required_fields(self):
        section = EssayNarrativeSection(
            title="Test Section",
            estimated_word_count=200,
        )
        assert section.title == "Test Section"
        assert section.estimated_word_count == 200
        assert section.talking_points == []
        assert section.coaching_tips == []

    def test_with_talking_points_and_tips(self):
        section = EssayNarrativeSection(
            title="Work Experience",
            estimated_word_count=150,
            talking_points=["Free clinic", "Shadowing"],
            coaching_tips=["Use active voice", "Quantify impact"],
        )
        assert len(section.talking_points) == 2
        assert len(section.coaching_tips) == 2


# ---------------------------------------------------------------------------
# Tests: LLMEssayOutline schema
# ---------------------------------------------------------------------------


class TestLLMEssayOutline:
    def test_has_four_sections(self):
        fields = LLMEssayOutline.model_fields
        assert "part_1_personal_story" in fields
        assert "part_2_work_experience" in fields
        assert "part_3_academic_citation" in fields
        assert "part_4_future_service" in fields

    def test_has_suggested_theme(self):
        fields = LLMEssayOutline.model_fields
        assert "suggested_theme" in fields

    def test_has_mission_alignment_angle(self):
        fields = LLMEssayOutline.model_fields
        assert "mission_alignment_angle" in fields


# ---------------------------------------------------------------------------
# Tests: Prompt structure
# ---------------------------------------------------------------------------


class TestPromptStructure:
    def test_system_prompt_contains_guardrail(self):
        assert "Do NOT write" in SYSTEM_PROMPT or "do NOT write" in SYSTEM_PROMPT

    def test_system_prompt_mentions_four_sections(self):
        assert "Personal Story" in SYSTEM_PROMPT
        assert "Work & Volunteer" in SYSTEM_PROMPT
        assert "Academic Foundation" in SYSTEM_PROMPT
        assert "Future Service" in SYSTEM_PROMPT

    def test_system_prompt_mentions_mission_alignment(self):
        assert "mission" in SYSTEM_PROMPT.lower()
        assert "core values" in SYSTEM_PROMPT.lower()

    def test_user_prompt_template_has_placeholders(self):
        assert "{scholarship_title}" in USER_PROMPT_TEMPLATE
        assert "{provider}" in USER_PROMPT_TEMPLATE
        assert "{provider_mission}" in USER_PROMPT_TEMPLATE
        assert "{core_values}" in USER_PROMPT_TEMPLATE
        assert "{prompt}" in USER_PROMPT_TEMPLATE
        assert "{word_limit}" in USER_PROMPT_TEMPLATE
        assert "{lived_experience}" in USER_PROMPT_TEMPLATE
        assert "{work_experience}" in USER_PROMPT_TEMPLATE
        assert "{academic_topics}" in USER_PROMPT_TEMPLATE


# ---------------------------------------------------------------------------
# Tests: generate_essay_outline (mocked LLM)
# ---------------------------------------------------------------------------


class TestGenerateEssayOutline:
    def test_returns_none_when_no_llm_configured(self):
        """When no OPENAI_API_KEY or LITELLM_MODEL is set, returns None."""
        with patch.dict("os.environ", {}, clear=True):
            req = EssayOutlineRequest(
                scholarship_title="Test",
                provider="Provider",
            )
            import asyncio
            result = asyncio.run(generate_essay_outline(req))
            assert result is None

    def test_returns_response_when_llm_succeeds(self):
        """When the LLM call succeeds, returns a valid EssayOutlineResponse."""
        # Build a mock LLM response
        mock_section = EssayNarrativeSection(
            title="Personal Story",
            estimated_word_count=150,
            talking_points=["Origin story", "Family background"],
            coaching_tips=["Be authentic", "Show don't tell"],
        )
        mock_llm_result = LLMEssayOutline(
            suggested_theme="From challenge to commitment",
            mission_alignment_angle="Connect your values to the provider's mission",
            part_1_personal_story=mock_section,
            part_2_work_experience=mock_section,
            part_3_academic_citation=mock_section,
            part_4_future_service=mock_section,
            checklist=["Proofread", "Check word count"],
        )

        # Mock the client
        mock_client = MagicMock()
        mock_create = AsyncMock(return_value=mock_llm_result)
        mock_client.chat.completions.create = mock_create

        with patch(
            "app.services.outline_service._build_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ):
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                req = EssayOutlineRequest(
                    scholarship_title="Pharmacy Award",
                    provider="APhA",
                    provider_mission="Advancing pharmacy",
                    provider_core_values=["equity"],
                )
                import asyncio
                result = asyncio.run(generate_essay_outline(req))

        assert result is not None
        assert isinstance(result, EssayOutlineResponse)
        assert result.suggested_theme == "From challenge to commitment"
        assert result.part_1_personal_story.talking_points == ["Origin story", "Family background"]
        assert len(result.checklist) == 2

    def test_returns_none_on_llm_failure(self):
        """When the LLM call raises, returns None."""
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API error"))

        with patch(
            "app.services.outline_service._build_client",
            return_value=(mock_client, "gpt-4o-mini"),
        ):
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                req = EssayOutlineRequest(
                    scholarship_title="Test",
                    provider="Provider",
                )
                import asyncio
                result = asyncio.run(generate_essay_outline(req))

        assert result is None
