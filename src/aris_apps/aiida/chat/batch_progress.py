"""Pure aggregation of AiiDA process nodes into session batch progress."""

from __future__ import annotations

import re
from typing import Any

_DEFAULT_SESSION_TITLE = "New Conversation"
_BATCH_PROCESS_TYPES = {
    "processnode",
    "workflownode",
    "workchainnode",
    "calcjobnode",
    "calcfunctionnode",
}
_BATCH_RUNNING_STATES = {"running"}
_BATCH_QUEUED_STATES = {"created", "waiting"}
_BATCH_FINISHED_STATES = {"finished", "completed", "success"}
_BATCH_FAILED_STATES = {"failed", "excepted", "killed", "error"}


def _coerce_optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and re.fullmatch(r"-?\d+", stripped):
            return int(stripped)
    return None


def _normalize_process_state_value(value: Any) -> str:
    return str(value or "").strip().replace("_", " ").lower()


def _is_batch_process_node(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False

    process_state = _normalize_process_state_value(entry.get("process_state") or entry.get("state"))
    if process_state and process_state != "n/a":
        return True

    for candidate in (entry.get("type"), entry.get("node_type"), entry.get("full_type")):
        normalized = str(candidate or "").strip().lower()
        if any(token in normalized for token in _BATCH_PROCESS_TYPES):
            return True

    process_label = str(entry.get("process_label") or "").strip()
    return bool(process_label and process_label.upper() != "N/A")


def _classify_batch_process_status(entry: dict[str, Any]) -> str | None:
    process_state = _normalize_process_state_value(entry.get("process_state") or entry.get("state"))
    exit_status = _coerce_optional_int(entry.get("exit_status"))

    if process_state in _BATCH_RUNNING_STATES:
        return "running"
    if process_state in _BATCH_QUEUED_STATES:
        return "queued"
    if process_state in _BATCH_FINISHED_STATES:
        return "success" if exit_status in (None, 0) else "failed"
    if process_state in _BATCH_FAILED_STATES:
        return "failed"
    if exit_status is not None and exit_status != 0:
        return "failed"
    if process_state:
        return "queued"
    return None


def _batch_process_label(entry: dict[str, Any]) -> str:
    for key in ("label", "process_label"):
        value = str(entry.get(key) or "").strip()
        if value and value.upper() != "N/A":
            return value
    pk = _coerce_optional_int(entry.get("pk"))
    return f"Process #{pk}" if pk is not None and pk > 0 else "Process"


def _summarize_chat_session_batch_progress(
    *,
    session_id: str,
    title: str,
    session_group_label: str,
    nodes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    status_rank = {"running": 0, "queued": 1, "failed": 2, "success": 3}
    items: list[dict[str, Any]] = []
    counts = {"success": 0, "running": 0, "queued": 0, "failed": 0}

    for entry in nodes:
        if not _is_batch_process_node(entry):
            continue
        status = _classify_batch_process_status(entry)
        if status is None:
            continue
        counts[status] += 1
        items.append(
            {
                "pk": _coerce_optional_int(entry.get("pk")) or 0,
                "label": _batch_process_label(entry),
                "process_label": str(entry.get("process_label") or "").strip() or None,
                "state": _normalize_process_state_value(entry.get("process_state") or entry.get("state"))
                or "unknown",
                "exit_status": _coerce_optional_int(entry.get("exit_status")),
                "status": status,
            }
        )

    total = len(items)
    if total <= 1:
        return None

    done = counts["success"] + counts["failed"]
    items.sort(key=lambda item: (status_rank.get(str(item["status"]), 99), item["pk"]))
    return {
        "session_id": session_id,
        "label": str(title or _DEFAULT_SESSION_TITLE),
        "group_label": session_group_label,
        "total": total,
        "done": done,
        "percent": max(0, min(100, int(round((done / total) * 100)))),
        **counts,
        "items": items,
    }


__all__ = [
    "_batch_process_label",
    "_classify_batch_process_status",
    "_coerce_optional_int",
    "_is_batch_process_node",
    "_normalize_process_state_value",
    "_summarize_chat_session_batch_progress",
]
