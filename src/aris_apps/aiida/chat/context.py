"""Normalization helpers for explicit chat context and preference payloads."""

from __future__ import annotations

import re
from typing import Any

_AUTO_ENVIRONMENT_PROMPT_MARKERS = (
    "current environment is",
    "available aiida",
    "submission draft generation is supported",
    "standard project layout",
    "codes/<filename>.py",
)


def normalize_context_node_ids(raw: Any) -> list[int]:
    if raw is None:
        return []

    values: list[Any]
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return []
        values = [part.strip() for part in stripped.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        values = list(raw)
    else:
        values = [raw]

    deduped: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        try:
            pk = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if pk <= 0 or pk in seen:
            continue
        seen.add(pk)
        deduped.append(pk)
        if len(deduped) >= 30:
            break
    return deduped


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


def _normalize_focus_context_nodes(raw_nodes: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_nodes, list):
        return []

    normalized: list[dict[str, Any]] = []
    seen: set[int] = set()
    for entry in raw_nodes:
        if not isinstance(entry, dict):
            continue
        pk = _coerce_positive_int(entry.get("pk"))
        if pk is None or pk in seen:
            continue
        seen.add(pk)

        label_raw = entry.get("label")
        label = str(label_raw).strip() if isinstance(label_raw, str) else ""
        node_type_raw = entry.get("node_type")
        node_type = str(node_type_raw).strip() if isinstance(node_type_raw, str) else ""
        formula_raw = entry.get("formula")
        formula = str(formula_raw).strip() if isinstance(formula_raw, str) else ""
        normalized.append(
            {
                "pk": pk,
                "label": label or f"#{pk}",
                "formula": formula or None,
                "node_type": node_type or "Unknown",
            }
        )
    return normalized


def _normalize_session_parameters(raw_parameters: Any) -> list[dict[str, str]]:
    values = raw_parameters if isinstance(raw_parameters, list) else []
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in values:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        value = str(entry.get("value") or "").strip()
        if not key or not value:
            continue
        lowered = key.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append({"key": key, "value": value})
    return normalized


def _looks_like_auto_environment_prompt_block(block: str) -> bool:
    lowered = " ".join(str(block or "").strip().lower().split())
    if not lowered:
        return False
    if "current environment is" not in lowered or "available aiida" not in lowered:
        return False
    return any(marker in lowered for marker in _AUTO_ENVIRONMENT_PROMPT_MARKERS[2:])


def _strip_auto_environment_prompt(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    blocks = [segment.strip() for segment in re.split(r"\n\s*\n+", text) if str(segment).strip()]
    if not blocks:
        return ""

    kept_blocks = [block for block in blocks if not _looks_like_auto_environment_prompt_block(block)]
    return "\n\n".join(kept_blocks).strip()


def _build_user_message_payload(
    metadata: dict[str, Any] | None,
    context_pks: list[int],
) -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    normalized_pks = normalize_context_node_ids(context_pks)
    if normalized_pks:
        payload["context_pks"] = normalized_pks

    context_nodes = _normalize_focus_context_nodes((metadata or {}).get("context_nodes"))
    if context_nodes:
        payload["context_nodes"] = context_nodes
    pinned_nodes = _normalize_focus_context_nodes((metadata or {}).get("pinned_nodes"))
    if pinned_nodes:
        payload["pinned_nodes"] = pinned_nodes
    session_environment = str((metadata or {}).get("session_environment") or "").strip().lower()
    if session_environment:
        payload["session_environment"] = session_environment
    session_prompt_override = (
        (metadata or {}).get("session_prompt_override")
        if isinstance((metadata or {}).get("session_prompt_override"), str)
        else None
    )
    prompt_override = _strip_auto_environment_prompt(
        session_prompt_override
        if session_prompt_override is not None
        else (metadata or {}).get("prompt_override")
    )
    if prompt_override:
        payload["prompt_override"] = prompt_override
    session_parameters = _normalize_session_parameters((metadata or {}).get("session_parameters"))
    if session_parameters:
        payload["session_parameters"] = session_parameters

    return payload or None


__all__ = [
    "_build_user_message_payload",
    "_coerce_positive_int",
    "_looks_like_auto_environment_prompt_block",
    "_normalize_focus_context_nodes",
    "_normalize_session_parameters",
    "_strip_auto_environment_prompt",
    "normalize_context_node_ids",
]
