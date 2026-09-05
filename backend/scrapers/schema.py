"""Canonical scholarship extraction record shared across parser stages."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class ScholarshipExtract(BaseModel):
    """Schema produced by deterministic and LLM parsers alike.

    `portal_url` and `provider` are set by the runner before DB upsert.
    Critical fields used to decide whether to invoke the LLM fallback:
    `title`, `award_amount`, `deadline`.
    """

    title: str
    provider: str = ""
    portal_url: str = ""
    award_amount: Optional[int] = None
    deadline: Optional[str] = None  # ISO YYYY-MM-DD
    eligible_disciplines: List[str] = []
    eligible_credentials: List[str] = []
    min_gpa: Optional[float] = None
    max_sai: Optional[int] = None
    state_restrictions: List[str] = []
    metro_restrictions: List[str] = []  # MSA names or "cbsa:XXXXX" codes
    required_affiliations: List[str] = []
    matching_tags: List[str] = []
    estimated_next_cycle: Optional[str] = None
    source: str = "deterministic"  # or "llm"
    # Source metadata (populated by the runner from SourceConfig)
    source_category: str = ""
    source_name: str = ""
    # Provider alignment & local discovery fields
    provider_type: Optional[str] = None
    provider_mission: Optional[str] = None
    provider_core_values: List[str] = []
    is_local: bool = False
    target_community: Optional[str] = None

    def is_critical_complete(self) -> bool:
        """Return True if all critical fields are populated and parseable."""
        return bool(self.title) and self.award_amount is not None and bool(self.deadline)


class ParseError(BaseModel):
    url: str
    reason: str
    stage: str = "deterministic"
