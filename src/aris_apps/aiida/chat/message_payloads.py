"""Pure merge rules for incremental assistant message payloads."""

from __future__ import annotations

from typing import Any


def _is_status_only_text(text: str) -> bool:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return False
    return all(
        line.lower().startswith("thinking:")
        or line.lower().startswith("running:")
        or line.lower().startswith("step:")
        or line.lower().startswith("⚙️ [step]")
        for line in lines
    )


def _merge_message_payload(
    existing_payload: dict[str, Any] | None,
    incoming_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(existing_payload, dict):
        return incoming_payload
    if not isinstance(incoming_payload, dict):
        return existing_payload

    merged = dict(existing_payload)
    for key, value in incoming_payload.items():
        if key == "tool_calls" and isinstance(merged.get("tool_calls"), list) and isinstance(value, list):
            deduped: list[str] = []
            seen: set[str] = set()
            for entry in [*merged["tool_calls"], *value]:
                cleaned = str(entry).strip()
                if not cleaned or cleaned in seen:
                    continue
                seen.add(cleaned)
                deduped.append(cleaned)
            merged["tool_calls"] = deduped
            continue
        if key == "status" and isinstance(merged.get("status"), dict) and isinstance(value, dict):
            merged_status = dict(merged["status"])
            for status_key, status_value in value.items():
                if (
                    status_key == "steps"
                    and isinstance(merged_status.get("steps"), list)
                    and isinstance(status_value, list)
                ):
                    deduped_steps: list[str] = []
                    seen_steps: set[str] = set()
                    for step in [*merged_status["steps"], *status_value]:
                        step_text = str(step).strip()
                        if not step_text or step_text in seen_steps:
                            continue
                        seen_steps.add(step_text)
                        deduped_steps.append(step_text)
                    merged_status["steps"] = deduped_steps
                else:
                    merged_status[status_key] = status_value
            merged["status"] = merged_status
            continue
        merged[key] = value
    return merged


__all__ = ["_is_status_only_text", "_merge_message_payload"]
