"""Guardrail settings. They live inside RagConfig, so they are versioned and activated like
the rest of the answer configuration (spec §4.2)."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ModerationCategory = Literal[
    "violence", "hate", "harassment", "sexual", "illegal", "weapons", "self_harm"
]
CategoryAction = Literal["block", "flag", "off"]

DEFAULT_SUPPORT_MESSAGE = (
    "It sounds like you may be going through something really difficult. You don't have to "
    "face it alone: please reach out to someone you trust or to a local crisis line. If you "
    "are in immediate danger, contact your local emergency number now."
)


def _default_moderation() -> dict[ModerationCategory, CategoryAction]:
    return {
        "violence": "block",
        "hate": "block",
        "harassment": "block",
        "sexual": "block",
        "illegal": "block",
        "weapons": "block",
        "self_harm": "flag",
    }


class PiiPattern(BaseModel):
    """A company-specific identifier to redact, e.g. employee numbers."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9_]+$")
    regex: str = Field(min_length=1, max_length=300)

    @field_validator("regex")
    @classmethod
    def _compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression: {exc}") from None
        return value


def _default_pii_patterns() -> list[PiiPattern]:
    # Example only: edit to the company's real employee-number format.
    return [PiiPattern(name="employee_number", regex=r"\bEMP-\d{6}\b")]


class GuardrailSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Input
    rate_limit_per_minute: int = Field(default=10, ge=1, le=600)
    max_question_chars: int = Field(default=2000, ge=10, le=4000)
    moderation: dict[ModerationCategory, CategoryAction] = Field(
        default_factory=_default_moderation
    )
    self_harm_support: bool = True
    injection_check: bool = True
    exfiltration_check: bool = True
    scope_check: bool = False
    scope_description: str = Field(default="", max_length=1000)
    classifier_model: str = Field(default="gpt-5-nano", min_length=1, max_length=100)
    blocked_message: str = Field(
        default="I can't help with that request.", min_length=1, max_length=500
    )
    off_topic_message: str = Field(
        default="I can only help with questions about the company's documents.",
        min_length=1,
        max_length=500,
    )
    support_message: str = Field(default=DEFAULT_SUPPORT_MESSAGE, min_length=1, max_length=2000)
    # Output
    pii_redaction: bool = True
    pii_patterns: list[PiiPattern] = Field(default_factory=_default_pii_patterns, max_length=20)
    system_prompt_leak_check: bool = True
    groundedness_check: bool = True
    judge_model: str = Field(default="gpt-5-nano", min_length=1, max_length=100)
    # Strikes and cost caps (0 = no cap)
    strike_limit: int = Field(default=3, ge=1, le=20)
    strike_window_hours: int = Field(default=24, ge=1, le=720)
    strike_lock_hours: int = Field(default=24, ge=1, le=720)
    user_daily_cost_usd: float = Field(default=2.0, ge=0)
    installation_daily_cost_usd: float = Field(default=50.0, ge=0)
    cost_alert_ratio: float = Field(default=0.8, gt=0, le=1)
