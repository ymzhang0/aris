"""Pure normalization and serialization helpers for ARIS chat sessions."""

from __future__ import annotations

from typing import Any

from src.aris_apps.aiida.chat.context import (
    _normalize_focus_context_nodes,
    _normalize_session_parameters,
    _strip_auto_environment_prompt,
)

MAX_CHAT_SESSION_MESSAGES = 200
MAX_CHAT_SESSION_TAGS = 12
MAX_CHAT_SESSION_TAG_LENGTH = 32


def trim_text(value: Any, *, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def normalize_chat_session_tags(raw_tags: Any) -> list[str]:
    if not isinstance(raw_tags, (list, tuple, set)):
        return []

    tags: list[str] = []
    seen: set[str] = set()
    for value in raw_tags:
        text = str(value or "").strip()
        if not text:
            continue
        normalized = text if text.startswith("#") else f"#{text}"
        normalized = trim_text(normalized, limit=MAX_CHAT_SESSION_TAG_LENGTH)
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        tags.append(normalized)
        if len(tags) >= MAX_CHAT_SESSION_TAGS:
            break
    return tags


def serialize_chat_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for message in history:
        item = {
            "role": str(message.get("role", "assistant")),
            "text": str(message.get("text", "")),
            "status": str(message.get("status", "done")),
            "turn_id": int(message.get("turn_id") or 0),
        }
        message_payload = message.get("payload")
        if isinstance(message_payload, dict):
            item["payload"] = message_payload
        payload.append(item)
    return payload


def normalize_chat_messages(raw_messages: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_messages, list):
        return []

    normalized: list[dict[str, Any]] = []
    for entry in raw_messages:
        if not isinstance(entry, dict):
            continue
        message = {
            "role": str(entry.get("role", "assistant")),
            "text": str(entry.get("text", "")),
            "status": str(entry.get("status", "done")),
            "turn_id": int(entry.get("turn_id") or 0),
        }
        payload = entry.get("payload")
        if isinstance(payload, dict):
            message["payload"] = payload
        normalized.append(message)
    return normalized[-MAX_CHAT_SESSION_MESSAGES:]


def normalize_chat_session_snapshot(raw_snapshot: Any) -> dict[str, Any]:
    snapshot = raw_snapshot if isinstance(raw_snapshot, dict) else {}
    context_nodes = _normalize_focus_context_nodes(snapshot.get("context_nodes"))
    pinned_nodes = _normalize_focus_context_nodes(snapshot.get("pinned_nodes"))

    selected_group_raw = snapshot.get("selected_group")
    selected_group = str(selected_group_raw).strip() if isinstance(selected_group_raw, str) else ""
    selected_model_raw = snapshot.get("selected_model")
    selected_model = str(selected_model_raw).strip() if isinstance(selected_model_raw, str) else ""
    session_environment_raw = snapshot.get("session_environment")
    session_environment = (
        str(session_environment_raw).strip().lower() if isinstance(session_environment_raw, str) else ""
    )
    prompt_override_raw = snapshot.get("session_prompt_override")
    if not isinstance(prompt_override_raw, str) or not prompt_override_raw.strip():
        prompt_override_raw = snapshot.get("prompt_override")
    prompt_override = _strip_auto_environment_prompt(prompt_override_raw)

    return {
        "context_nodes": context_nodes,
        "pinned_nodes": pinned_nodes,
        "selected_group": selected_group or None,
        "selected_model": selected_model or None,
        "session_environment": session_environment or None,
        "session_environment_auto": bool(snapshot.get("session_environment_auto", True)),
        "environment_python_path": str(snapshot.get("environment_python_path") or "").strip() or None,
        "environment_active_python_path": (
            str(snapshot.get("environment_active_python_path") or "").strip() or None
        ),
        "prompt_override": prompt_override or None,
        "session_parameters": _normalize_session_parameters(snapshot.get("session_parameters")),
    }


__all__ = [
    "MAX_CHAT_SESSION_MESSAGES",
    "MAX_CHAT_SESSION_TAG_LENGTH",
    "MAX_CHAT_SESSION_TAGS",
    "normalize_chat_messages",
    "normalize_chat_session_snapshot",
    "normalize_chat_session_tags",
    "serialize_chat_history",
    "trim_text",
]
