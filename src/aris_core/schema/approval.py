"""Typed user-approval protocol for consequential ARIS actions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

ApprovalAction = Literal["submission.execute"]
ApprovalDecisionValue = Literal["approved", "rejected"]
ApprovalScope = Literal["single", "batch", "pending"]


def submission_resource_digest(draft: Any) -> str:
    """Return a stable digest that binds an approval to the submitted payload."""

    serialized = json.dumps(
        draft,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class ApprovalRequest(BaseModel):
    """A UI-visible request for an explicit user decision."""

    protocol_version: Literal["1"] = "1"
    approval_id: str = Field(default_factory=lambda: uuid4().hex)
    action: ApprovalAction = "submission.execute"
    status: Literal["pending"] = "pending"
    scope: ApprovalScope
    resource_digest: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    summary: str | None = None


class ApprovalDecision(BaseModel):
    """A durable, machine-readable decision supplied by the UI."""

    protocol_version: Literal["1"] = "1"
    approval_id: str
    action: ApprovalAction = "submission.execute"
    decision: ApprovalDecisionValue
    scope: ApprovalScope
    actor_type: Literal["user"] = "user"
    decided_at: datetime
    resource_digest: str | None = None


class ApprovalAudit(BaseModel):
    """Normalized approval data recorded at the execution boundary."""

    protocol_version: Literal["1"] = "1"
    approval_id: str
    action: ApprovalAction = "submission.execute"
    decision: Literal["approved"] = "approved"
    scope: Literal["single", "batch"]
    actor_type: Literal["user"] = "user"
    decided_at: datetime
    resource_digest: str


def build_submission_approval_request(
    draft: Any,
    *,
    scope: Literal["single", "batch"],
) -> ApprovalRequest:
    return ApprovalRequest(
        scope=scope,
        resource_digest=submission_resource_digest(draft),
        summary="Submit the prepared AiiDA workflow" if scope == "single" else "Submit the prepared AiiDA batch",
    )


def resolve_submission_approval(
    decision: ApprovalDecision,
    draft: Any,
    *,
    expected_scope: Literal["single", "batch"],
) -> ApprovalAudit:
    """Validate an explicit decision bound to the submitted draft."""

    if decision is None:
        raise ValueError("Explicit submission approval is required")
    digest = submission_resource_digest(draft)
    if decision.decision != "approved":
        raise ValueError("Submission approval decision must be approved")
    if decision.scope != expected_scope:
        raise ValueError(f"Submission approval scope must be {expected_scope}")
    if decision.resource_digest and decision.resource_digest != digest:
        raise ValueError("Submission draft changed after it was approved")
    return ApprovalAudit(
        approval_id=decision.approval_id,
        scope=expected_scope,
        actor_type=decision.actor_type,
        decided_at=decision.decided_at,
        resource_digest=digest,
    )


__all__ = [
    "ApprovalAction",
    "ApprovalAudit",
    "ApprovalDecision",
    "ApprovalDecisionValue",
    "ApprovalRequest",
    "ApprovalScope",
    "build_submission_approval_request",
    "resolve_submission_approval",
    "submission_resource_digest",
]
