from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.aris_core.schema.approval import (
    ApprovalDecision,
    build_submission_approval_request,
    resolve_submission_approval,
    submission_resource_digest,
)


def _approved_decision(*, digest: str, scope: str = "single") -> ApprovalDecision:
    return ApprovalDecision(
        approval_id="approval-1",
        decision="approved",
        scope=scope,
        actor_type="user",
        decided_at=datetime.now(timezone.utc),
        resource_digest=digest,
    )


def test_submission_digest_is_stable_across_mapping_order() -> None:
    first = {"inputs": {"structure_pk": 7, "code": "pw@local"}, "entry_point": "pw.relax"}
    second = {"entry_point": "pw.relax", "inputs": {"code": "pw@local", "structure_pk": 7}}

    assert submission_resource_digest(first) == submission_resource_digest(second)


def test_approval_request_is_explicit_and_bound_to_draft() -> None:
    draft = {"entry_point": "pw.relax", "inputs": {"structure_pk": 7}}

    request = build_submission_approval_request(draft, scope="single")

    assert request.action == "submission.execute"
    assert request.status == "pending"
    assert request.scope == "single"
    assert request.resource_digest == submission_resource_digest(draft)


def test_resolve_submission_approval_rejects_modified_draft() -> None:
    original = {"inputs": {"structure_pk": 7}}
    modified = {"inputs": {"structure_pk": 8}}
    decision = _approved_decision(digest=submission_resource_digest(original))

    with pytest.raises(ValueError, match="changed after it was approved"):
        resolve_submission_approval(decision, modified, expected_scope="single")


def test_resolve_submission_approval_rejects_wrong_scope() -> None:
    draft = [{"inputs": {"structure_pk": 7}}]
    decision = _approved_decision(
        digest=submission_resource_digest(draft),
        scope="single",
    )

    with pytest.raises(ValueError, match="scope must be batch"):
        resolve_submission_approval(decision, draft, expected_scope="batch")


def test_approval_schema_rejects_unrecognized_decision() -> None:
    with pytest.raises(ValidationError):
        ApprovalDecision(
            approval_id="approval-1",
            decision="allow",
            scope="single",
            decided_at=datetime.now(timezone.utc),
        )


def test_submission_without_explicit_approval_is_rejected() -> None:
    with pytest.raises(ValueError, match="Explicit submission approval is required"):
        resolve_submission_approval(
            None,  # type: ignore[arg-type]
            {"inputs": {"structure_pk": 7}},
            expected_scope="single",
        )


def test_submission_decision_without_resource_digest_is_rejected() -> None:
    with pytest.raises(
        ValidationError,
        match="requires a resource digest",
    ):
        ApprovalDecision(
            approval_id="approval-1",
            decision="approved",
            scope="single",
            decided_at=datetime.now(timezone.utc),
        )


def test_pending_cancellation_cannot_carry_submission_digest() -> None:
    with pytest.raises(
        ValidationError,
        match="cannot include a resource digest",
    ):
        ApprovalDecision(
            approval_id="approval-1",
            decision="rejected",
            scope="pending",
            decided_at=datetime.now(timezone.utc),
            resource_digest="not-applicable",
        )
