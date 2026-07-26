"""Pure rules for the explicit ARIS submission protocol."""

from __future__ import annotations

from typing import Any, Mapping, Literal

TaskMode = Literal["none", "single", "batch"]


def _coerce_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            parsed = int(stripped)
            return parsed if parsed > 0 else None
    return None


def normalize_task_mode(value: Any) -> TaskMode:
    cleaned = str(value or "").strip().lower()
    if cleaned in {"single", "batch", "none"}:
        return cleaned  # type: ignore[return-value]
    return "none"


def normalize_submission_request(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None

    mode = normalize_task_mode(value.get("mode"))
    if mode not in {"single", "batch"}:
        return None

    workchain = str(value.get("workchain") or "").strip()
    code = str(value.get("code") or "").strip()
    protocol = str(value.get("protocol") or "moderate").strip() or "moderate"
    if not workchain or not code:
        return None

    normalized: dict[str, Any] = {
        "mode": mode,
        "workchain": workchain,
        "code": code,
        "protocol": protocol,
    }

    if mode == "single":
        structure_pk = _coerce_positive_int(value.get("structure_pk"))
        if structure_pk is None:
            return None
        normalized["structure_pk"] = structure_pk
    else:
        raw_structure_pks = value.get("structure_pks")
        if not isinstance(raw_structure_pks, list):
            return None
        structure_pks = [_coerce_positive_int(item) for item in raw_structure_pks]
        structure_pks = [item for item in structure_pks if item is not None]
        if not structure_pks:
            return None
        normalized["structure_pks"] = structure_pks
        matrix_mode = str(value.get("matrix_mode") or "product").strip().lower() or "product"
        normalized["matrix_mode"] = "zip" if matrix_mode == "zip" else "product"

    for key in ("overrides", "protocol_kwargs", "parameter_grid"):
        raw = value.get(key)
        if isinstance(raw, Mapping):
            normalized[key] = dict(raw)

    return normalized


def submission_draft_is_batch(submission_draft: dict[str, Any] | None) -> bool:
    if not isinstance(submission_draft, dict):
        return False
    if isinstance(submission_draft.get("jobs"), list) and len(submission_draft["jobs"]) > 1:
        return True
    if isinstance(submission_draft.get("batch_aggregation"), dict):
        return True
    meta = submission_draft.get("meta")
    if not isinstance(meta, dict):
        return False
    raw_draft = meta.get("draft")
    if isinstance(raw_draft, list) and len(raw_draft) > 1:
        return True
    job_count = _coerce_positive_int(meta.get("job_count"))
    if job_count is not None and job_count > 1:
        return True
    structure_pks = meta.get("structure_pks")
    return isinstance(structure_pks, list) and len(structure_pks) > 1


def extract_recovery_plan(submission_draft: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(submission_draft, dict):
        return None
    meta = submission_draft.get("meta")
    if not isinstance(meta, dict):
        return None
    recovery_plan = meta.get("recovery_plan")
    return recovery_plan if isinstance(recovery_plan, dict) and recovery_plan else None


def render_submission_blocker_message(
    *,
    task_mode: str | None,
    recovery_plan: dict[str, Any] | None,
    next_step: str | None,
) -> str | None:
    if not isinstance(recovery_plan, dict) or not recovery_plan:
        return None

    normalized_mode = normalize_task_mode(task_mode)
    if normalized_mode not in {"single", "batch"}:
        return None

    mode_label = "batch submission preview" if normalized_mode == "batch" else "submission preview"
    lines = [f"ARIS could not prepare the {mode_label} yet."]

    summary = str(recovery_plan.get("summary") or "").strip()
    if summary:
        lines.extend(("", f"Blocked reason: {summary}"))

    issues = recovery_plan.get("issues")
    if isinstance(issues, list) and issues:
        visible_issues = [
            str(issue.get("message") or "").strip()
            for issue in issues[:3]
            if isinstance(issue, dict) and str(issue.get("message") or "").strip()
        ]
        if visible_issues:
            lines.extend(("", "Reported issues:"))
            lines.extend(f"- {message}" for message in visible_issues)

    if isinstance(next_step, str) and next_step.strip():
        lines.extend(("", f"Next step: {next_step.strip()}"))

    return "\n".join(lines).strip()


__all__ = [
    "TaskMode",
    "extract_recovery_plan",
    "normalize_submission_request",
    "normalize_task_mode",
    "render_submission_blocker_message",
    "submission_draft_is_batch",
]
