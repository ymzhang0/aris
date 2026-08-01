from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def _payload_contains_submission_preview(payload: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(payload, dict):
        return False
    if isinstance(payload.get("submission_draft"), dict) or isinstance(payload.get("submission_draft"), list):
        return True
    return False


class StructureResolution(BaseModel):
    """Machine-readable state for resolving a calculation structure prerequisite."""

    status: Literal[
        "existing",
        "search_required",
        "selection_required",
        "selected",
        "imported",
        "unavailable",
    ]
    query: Optional[Dict[str, Any]] = None
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    selected: Optional[Dict[str, Any]] = None
    import_receipt: Optional[Dict[str, Any]] = None


class ARISResponse(BaseModel):
    answer: str = Field(description="Natural language summary of the result.")
    thought_process: List[str] = Field(description="Step-by-step logic summary.")
    task_mode: Literal["none", "single", "batch"] = Field(
        default="none",
        description="Machine-readable task topology marker for this turn.",
    )
    submission_request: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional machine-readable submission request for protocol-driven preview preparation.",
    )
    research_plan: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional machine-readable scientific plan with title, objective, stages, "
            "assumptions, and expected outputs. Required for new submission preparation "
            "when enough information is available."
        ),
    )
    structure_resolution: Optional[StructureResolution] = Field(
        default=None,
        description=(
            "Explicit state of structure discovery, selection, and import when a "
            "calculation requires a structure prerequisite."
        ),
    )
    data_payload: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Raw data resulting from tool calls.",
    )
    is_successful: bool = Field(default=True)
    suggestions: List[str] = Field(
        default_factory=list,
        description="Actionable next steps for the user. Each must be < 5 words.",
    )

    @field_validator("suggestions")
    @classmethod
    def validate_suggestions(cls, value: List[str]) -> List[str]:
        for item in value:
            word_count = len(item.split())
            if word_count > 5:
                raise ValueError(
                    f"Suggestion '{item}' is too long ({word_count} words). "
                    "Keep it under 5 words for the compact action UI."
                )
        return value

    @model_validator(mode="after")
    def validate_preview_protocol(self) -> "ARISResponse":
        if self.task_mode in {"single", "batch"}:
            if self.submission_request is None and not _payload_contains_submission_preview(self.data_payload):
                raise ValueError(
                    "Responses with task_mode='single' or task_mode='batch' must include either "
                    "submission_request or a ready submission_draft in data_payload."
                )
        return self

__all__ = ["ARISResponse", "StructureResolution"]
