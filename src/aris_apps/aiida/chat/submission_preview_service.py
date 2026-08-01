"""Application service for structured submission preview preparation."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable

from src.aris_apps.aiida.domain.submissions import (
    extract_recovery_plan,
    normalize_submission_request,
    normalize_task_mode,
    render_submission_blocker_message,
)
from src.aris_core.schema.approval import build_submission_approval_request

NormalizeDraft = Callable[[dict[str, Any]], dict[str, Any]]
ApplyOverview = Callable[..., dict[str, Any]]
IsBatchDraft = Callable[[dict[str, Any] | None], bool]


@dataclass(frozen=True)
class SubmissionPreviewRules:
    """Pure preview rules supplied by the submission domain implementation."""

    normalize_draft: NormalizeDraft
    apply_overview: ApplyOverview
    is_batch_draft: IsBatchDraft


class SubmissionPreviewService:
    """Coordinates structured preview preparation and UI payload creation."""

    def __init__(self, rules: SubmissionPreviewRules) -> None:
        self._rules = rules

    @staticmethod
    def normalize_task_mode(value: Any) -> str:
        return normalize_task_mode(value)

    @staticmethod
    def normalize_request(value: Any) -> dict[str, Any] | None:
        return normalize_submission_request(value)

    async def prepare_request(
        self,
        request: dict[str, Any] | None,
        deps: Any,
        tool_calls: list[str] | None = None,
    ) -> dict[str, Any] | None:
        normalized_request = self.normalize_request(request)
        if not normalized_request:
            return None

        from src.aris_apps.aiida.agent import researcher as researcher_module

        ctx = SimpleNamespace(deps=deps)
        mode = normalized_request["mode"]
        if tool_calls is not None:
            tool_calls.append(
                "AUTO submit_new_batch_workflow"
                if mode == "batch"
                else "AUTO submit_new_workflow"
            )

        if mode == "batch":
            return await researcher_module.submit_new_batch_workflow(
                ctx,
                workchain=str(normalized_request["workchain"]),
                structure_pks=list(normalized_request["structure_pks"]),
                code=str(normalized_request["code"]),
                protocol=str(normalized_request["protocol"]),
                overrides=dict(normalized_request.get("overrides") or {}),
                protocol_kwargs=dict(
                    normalized_request.get("protocol_kwargs") or {}
                ),
                parameter_grid=dict(
                    normalized_request.get("parameter_grid") or {}
                )
                or None,
                matrix_mode=str(
                    normalized_request.get("matrix_mode") or "product"
                ),
            )

        return await researcher_module.submit_new_workflow(
            ctx,
            workchain=str(normalized_request["workchain"]),
            structure_pk=int(normalized_request["structure_pk"]),
            code=str(normalized_request["code"]),
            protocol=str(normalized_request["protocol"]),
            overrides=dict(normalized_request.get("overrides") or {}),
            protocol_kwargs=dict(normalized_request.get("protocol_kwargs") or {}),
        )

    def extract_submission_draft(
        self,
        output_payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        raw_submission = output_payload.get("submission_draft")
        if not isinstance(raw_submission, dict):
            return None
        return self._rules.normalize_draft(raw_submission)

    @staticmethod
    def _extract_recovery_payload(
        output_payload: dict[str, Any] | None,
        submission_draft: dict[str, Any] | None,
    ) -> tuple[dict[str, Any] | None, str | None, str | None]:
        recovery_plan: dict[str, Any] | None = None
        next_step: str | None = None
        status: str | None = None

        if isinstance(output_payload, dict):
            raw_status = output_payload.get("status")
            if isinstance(raw_status, str) and raw_status.strip():
                status = raw_status.strip()
            raw_next_step = output_payload.get("next_step")
            if isinstance(raw_next_step, str) and raw_next_step.strip():
                next_step = raw_next_step.strip()
            direct_plan = output_payload.get("recovery_plan")
            if isinstance(direct_plan, dict) and direct_plan:
                recovery_plan = direct_plan
            details = output_payload.get("details")
            if recovery_plan is None and isinstance(details, dict):
                nested_plan = details.get("recovery_plan")
                if isinstance(nested_plan, dict) and nested_plan:
                    recovery_plan = nested_plan

        if recovery_plan is None:
            recovery_plan = extract_recovery_plan(submission_draft)
        return recovery_plan, next_step, status

    @staticmethod
    def render_blocker_message(
        *,
        task_mode: str | None,
        recovery_plan: dict[str, Any] | None,
        next_step: str | None,
    ) -> str | None:
        return render_submission_blocker_message(
            task_mode=task_mode,
            recovery_plan=recovery_plan,
            next_step=next_step,
        )

    def build_message_payload(
        self,
        output: Any,
        *,
        tool_calls: list[str] | None = None,
        task_mode: str | None = None,
    ) -> dict[str, Any] | None:
        combined: dict[str, Any] = {}
        forced_batch_block = False
        output_payload = getattr(output, "data_payload", None)
        research_plan = getattr(output, "research_plan", None)
        if isinstance(research_plan, dict) and research_plan:
            combined["research_plan"] = research_plan
        structure_resolution = getattr(output, "structure_resolution", None)
        if structure_resolution is not None:
            model_dump = getattr(structure_resolution, "model_dump", None)
            if callable(model_dump):
                structure_resolution = model_dump(mode="json")
            if isinstance(structure_resolution, dict) and structure_resolution:
                combined["structure_resolution"] = structure_resolution
        if isinstance(output_payload, dict):
            combined["data_payload"] = output_payload
        if tool_calls:
            normalized_calls: list[str] = []
            for call in tool_calls:
                cleaned = str(call).strip()
                if not cleaned:
                    continue
                if normalized_calls and normalized_calls[-1] == cleaned:
                    continue
                normalized_calls.append(cleaned)
            if normalized_calls:
                combined["tool_calls"] = normalized_calls

        resolved_submission_draft = (
            self.extract_submission_draft(output_payload)
            if isinstance(output_payload, dict)
            else None
        )
        resolved_task_mode = self.normalize_task_mode(task_mode)
        if resolved_task_mode == "none":
            if isinstance(resolved_submission_draft, dict):
                resolved_task_mode = (
                    "batch"
                    if self._rules.is_batch_draft(resolved_submission_draft)
                    else "single"
                )
            elif isinstance(output_payload, dict):
                resolved_task_mode = self.normalize_task_mode(
                    output_payload.get("task_mode")
                )

        if isinstance(resolved_submission_draft, dict):
            resolved_submission_draft = self._rules.apply_overview(
                resolved_submission_draft,
                preferred_mode=resolved_task_mode,
            )

        if (
            resolved_task_mode == "batch"
            and isinstance(resolved_submission_draft, dict)
            and not self._rules.is_batch_draft(resolved_submission_draft)
        ):
            resolved_submission_draft = None
            forced_batch_block = True

        if isinstance(resolved_submission_draft, dict):
            combined["type"] = "SUBMISSION_DRAFT"
            combined["submission_draft"] = resolved_submission_draft
            approval_scope = (
                "batch" if resolved_task_mode == "batch" else "single"
            )
            approval_resource: Any = resolved_submission_draft
            approval_meta = resolved_submission_draft.get("meta")
            if isinstance(approval_meta, dict) and approval_meta.get("draft"):
                approval_resource = approval_meta["draft"]
            combined["approval_request"] = build_submission_approval_request(
                approval_resource,
                scope=approval_scope,
            ).model_dump(mode="json")
        combined["task_mode"] = resolved_task_mode

        recovery_plan, next_step, status = self._extract_recovery_payload(
            output_payload if isinstance(output_payload, dict) else None,
            resolved_submission_draft,
        )
        if forced_batch_block:
            recovery_plan = {
                "status": "blocked",
                "summary": (
                    "This request requires a batch submission draft, but only "
                    "a single-job draft was produced."
                ),
                "issues": [
                    {
                        "type": "batch_draft_required",
                        "message": (
                            "Do not present a single-job submission draft for "
                            "a multi-structure request."
                        ),
                    }
                ],
                "recommended_actions": [
                    {
                        "action": "submit_new_batch_workflow",
                        "reason": (
                            "Prepare one batch draft that contains the full "
                            "structure set."
                        ),
                    }
                ],
                "user_decision_required": False,
            }
            next_step = (
                "Prepare a batch submission draft for the full structure list "
                "before showing any launch button."
            )
            status = "SUBMISSION_BLOCKED"
        if isinstance(recovery_plan, dict) and recovery_plan:
            combined["recovery_plan"] = recovery_plan
        if isinstance(next_step, str) and next_step:
            combined["next_step"] = next_step
        if isinstance(status, str) and status:
            combined["status"] = status
        return combined or None


__all__ = ["SubmissionPreviewRules", "SubmissionPreviewService"]
