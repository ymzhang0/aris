"""Pure naming and lifecycle rules for ARIS chat session titles."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

from src.aris_apps.aiida.chat.session_models import (
    normalize_chat_messages,
    normalize_chat_session_snapshot,
    trim_text,
)

DEFAULT_SESSION_TITLE = "New Conversation"
SESSION_SLUG_MAX_LENGTH = 48
TITLE_MAX_LENGTH = 24
TITLE_RESEARCH_CHARS_LIMIT = 12

TITLE_STATE_IDLE = "idle"
TITLE_STATE_PENDING = "pending"
TITLE_STATE_READY = "ready"
TITLE_STATE_FAILED = "failed"

TITLE_STAGE_INITIAL = "initial"
TITLE_STAGE_DEEP_SUMMARY = "deep_summary"
TITLE_STAGE_CONTEXT_SWITCH = "context_switch"

TITLE_GENERATOR_SYSTEM_PROMPT = (
    "You are a scientific research assistant. Generate one very short English session title."
    " The title must use ASCII only."
    " Prefer 2-4 concise English words."
    " Keep material abbreviations or node numbers when useful, such as Si Bands, GaAs Relax, Node 101."
    " The title must describe the research object or task."
    " Prefer the pinned/context nodes when available."
    " Output only the title itself. No Chinese. No quotes. No markdown. No explanation."
)


def normalize_title_state(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in {TITLE_STATE_PENDING, TITLE_STATE_READY, TITLE_STATE_FAILED}:
        return cleaned
    return TITLE_STATE_IDLE


def looks_like_session_identifier_title(title: Any, session_id: Any) -> bool:
    cleaned_title = str(title or "").strip()
    cleaned_session_id = str(session_id or "").strip()
    if not cleaned_title:
        return False
    if cleaned_session_id and cleaned_title == cleaned_session_id:
        return True
    return bool(
        re.fullmatch(r"[0-9a-f]{32}", cleaned_title, flags=re.IGNORECASE)
        or re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            cleaned_title,
            flags=re.IGNORECASE,
        )
    )


def ascii_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return normalized.encode("ascii", "ignore").decode("ascii")


def sanitize_session_title_text(value: Any) -> str:
    text = ascii_text(value)
    text = text.replace("\n", " ").replace("\r", " ")
    text = re.sub(r"^title[:：\s-]*", "", text, flags=re.IGNORECASE).strip()
    text = text.strip("`'\"“”‘’[](){}")
    text = re.sub(r"[^A-Za-z0-9#()+._ -]+", " ", text)
    text = " ".join(text.split())
    return text.strip(" -_.")


def normalize_session_title(
    value: Any,
    *,
    fallback: str = DEFAULT_SESSION_TITLE,
    max_length: int = 80,
) -> str:
    text = sanitize_session_title_text(value)
    if not text:
        text = sanitize_session_title_text(fallback) or DEFAULT_SESSION_TITLE
    return text[:max_length].strip() or (
        sanitize_session_title_text(fallback) or DEFAULT_SESSION_TITLE
    )


def slugify_session_name(value: Any, *, fallback: str = "session") -> str:
    text = ascii_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    text = text[:SESSION_SLUG_MAX_LENGTH].strip("-")
    return text or fallback


def summarize_focus_node_for_title(node: dict[str, Any] | None) -> str:
    if not isinstance(node, dict):
        return ""

    formula = trim_text(node.get("formula") or "", limit=24)
    label = trim_text(node.get("label") or "", limit=24)
    subject = formula or label
    if not subject:
        return ""

    try:
        pk = int(node.get("pk") or 0)
    except (TypeError, ValueError):
        pk = 0
    if pk > 0:
        return f"{subject} #{pk}"
    return subject


def pick_title_focus_node(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    normalized_snapshot = normalize_chat_session_snapshot(snapshot)
    pinned_nodes = normalized_snapshot.get("pinned_nodes") or []
    if pinned_nodes:
        return pinned_nodes[0]
    context_nodes = normalized_snapshot.get("context_nodes") or []
    if context_nodes:
        return context_nodes[0]
    return None


def derive_chat_session_title(intent: str, snapshot: dict[str, Any] | None = None) -> str:
    cleaned = " ".join(str(intent or "").split())
    if not cleaned:
        return DEFAULT_SESSION_TITLE

    focus_subject = summarize_focus_node_for_title(pick_title_focus_node(snapshot))
    if focus_subject:
        lowered = cleaned.lower()
        if any(keyword in cleaned for keyword in ("结构", "structure")):
            return trim_text(f"查看 {focus_subject}", limit=TITLE_MAX_LENGTH) or DEFAULT_SESSION_TITLE
        if any(keyword in lowered for keyword in ("band", "bands")) or "能带" in cleaned:
            return trim_text(f"{focus_subject} 能带", limit=TITLE_MAX_LENGTH) or DEFAULT_SESSION_TITLE
        return trim_text(focus_subject, limit=TITLE_MAX_LENGTH) or DEFAULT_SESSION_TITLE

    first_line = cleaned.splitlines()[0].strip(" -:;,.")
    return trim_text(first_line or cleaned, limit=48) or DEFAULT_SESSION_TITLE


def count_session_user_turns(session: dict[str, Any] | None) -> int:
    if not isinstance(session, dict):
        return 0
    messages = normalize_chat_messages(session.get("messages"))
    return sum(1 for message in messages if message.get("role") == "user")


def extract_first_session_message_text(session: dict[str, Any] | None, role: str) -> str:
    if not isinstance(session, dict):
        return ""
    for message in normalize_chat_messages(session.get("messages")):
        if str(message.get("role") or "") == role:
            return str(message.get("text") or "").strip()
    return ""


def extract_latest_session_message_text(session: dict[str, Any] | None, role: str) -> str:
    if not isinstance(session, dict):
        return ""
    for message in reversed(normalize_chat_messages(session.get("messages"))):
        if str(message.get("role") or "") == role:
            return str(message.get("text") or "").strip()
    return ""


def serialize_title_context_nodes(nodes: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for node in nodes[:4]:
        if not isinstance(node, dict):
            continue
        pk = node.get("pk")
        formula = str(node.get("formula") or "").strip()
        label = str(node.get("label") or "").strip()
        node_type = str(node.get("node_type") or "").strip()
        summary = formula or label or node_type or "Unknown node"
        if pk:
            summary = f"{summary} (#{pk})"
        if node_type and node_type not in summary:
            summary = f"{summary}, type={node_type}"
        lines.append(summary)
    return lines


def build_title_context_key(snapshot: dict[str, Any] | None) -> str:
    normalized_snapshot = normalize_chat_session_snapshot(snapshot)
    parts: list[str] = []
    pinned_nodes = normalized_snapshot.get("pinned_nodes") or []
    context_nodes = normalized_snapshot.get("context_nodes") or []
    for node in [*pinned_nodes[:2], *context_nodes[:2]]:
        if not isinstance(node, dict):
            continue
        parts.append(
            "|".join(
                [
                    str(node.get("pk") or ""),
                    str(node.get("formula") or ""),
                    str(node.get("label") or ""),
                    str(node.get("node_type") or ""),
                ]
            )
        )
    selected_group = str(normalized_snapshot.get("selected_group") or "").strip()
    if selected_group:
        parts.append(f"group:{selected_group}")
    session_environment = str(normalized_snapshot.get("session_environment") or "").strip()
    if session_environment:
        parts.append(f"env:{session_environment}")
    if not parts:
        return ""
    return hashlib.sha1(
        "\n".join(parts).encode("utf-8", errors="replace")
    ).hexdigest()


def sanitize_generated_title(raw_title: Any, fallback: str) -> str:
    text = normalize_session_title(
        raw_title,
        fallback=fallback,
        max_length=TITLE_MAX_LENGTH,
    )
    if len(text) > TITLE_RESEARCH_CHARS_LIMIT and "#" not in text and "(" not in text:
        text = text[:TITLE_RESEARCH_CHARS_LIMIT].strip()
    return text or fallback


def build_title_generation_prompt(
    session: dict[str, Any],
    *,
    stage: str,
    completed_turn_id: int,
) -> str:
    snapshot = normalize_chat_session_snapshot(session.get("snapshot"))
    first_user_intent = (
        str(session.get("title_first_intent") or "").strip()
        or extract_first_session_message_text(session, "user")
    )
    latest_user_intent = extract_latest_session_message_text(session, "user")
    latest_assistant_reply = trim_text(
        extract_latest_session_message_text(session, "assistant"),
        limit=180,
    )
    pinned_lines = serialize_title_context_nodes(snapshot.get("pinned_nodes") or [])
    context_lines = serialize_title_context_nodes(snapshot.get("context_nodes") or [])
    selected_group = str(snapshot.get("selected_group") or "").strip()
    session_environment = str(snapshot.get("session_environment") or "").strip()
    current_title = str(session.get("title") or DEFAULT_SESSION_TITLE)
    stage_label = {
        TITLE_STAGE_INITIAL: "Initial Naming",
        TITLE_STAGE_DEEP_SUMMARY: "Deep Summary",
        TITLE_STAGE_CONTEXT_SWITCH: "Context Switch",
    }.get(stage, "Session Summary")

    prompt_lines = [
        TITLE_GENERATOR_SYSTEM_PROMPT,
        "",
        f"Stage: {stage_label}",
        f"Turn: {completed_turn_id}",
        f"Current title: {current_title}",
        f"First user request: {first_user_intent or 'None'}",
        f"Latest user request: {latest_user_intent or first_user_intent or 'None'}",
    ]
    if latest_assistant_reply:
        prompt_lines.append(f"Latest assistant summary: {latest_assistant_reply}")
    if selected_group:
        prompt_lines.append(f"Selected group: {selected_group}")
    if session_environment:
        prompt_lines.append(f"Environment: {session_environment}")
    if pinned_lines:
        prompt_lines.append("Pinned Context:")
        prompt_lines.extend(f"- {line}" for line in pinned_lines)
    if context_lines:
        prompt_lines.append("Attached Context:")
        prompt_lines.extend(f"- {line}" for line in context_lines)
    prompt_lines.extend(["", "Return the final English title only."])
    return "\n".join(prompt_lines)


def should_schedule_title_generation(
    session: dict[str, Any],
    completed_turn_id: int,
) -> str | None:
    if not bool(session.get("auto_title", False)):
        return None
    if normalize_title_state(session.get("title_state")) == TITLE_STATE_PENDING:
        return None

    user_turn_count = count_session_user_turns(session)
    last_generated_turn = int(session.get("title_last_generated_turn") or 0)
    generation_count = max(0, int(session.get("title_generation_count") or 0))
    context_key = build_title_context_key(session.get("snapshot"))
    last_context_key = str(session.get("title_last_context_key") or "").strip()

    if user_turn_count <= 1 and generation_count == 0 and completed_turn_id > last_generated_turn:
        return TITLE_STAGE_INITIAL
    if (
        context_key
        and last_context_key
        and context_key != last_context_key
        and completed_turn_id > last_generated_turn
    ):
        return TITLE_STAGE_CONTEXT_SWITCH
    if user_turn_count > 5 and generation_count < 2 and completed_turn_id > last_generated_turn:
        return TITLE_STAGE_DEEP_SUMMARY
    return None


__all__ = [
    "DEFAULT_SESSION_TITLE",
    "SESSION_SLUG_MAX_LENGTH",
    "TITLE_MAX_LENGTH",
    "TITLE_RESEARCH_CHARS_LIMIT",
    "TITLE_STAGE_CONTEXT_SWITCH",
    "TITLE_STAGE_DEEP_SUMMARY",
    "TITLE_STAGE_INITIAL",
    "TITLE_STATE_FAILED",
    "TITLE_STATE_IDLE",
    "TITLE_STATE_PENDING",
    "TITLE_STATE_READY",
    "ascii_text",
    "build_title_context_key",
    "build_title_generation_prompt",
    "count_session_user_turns",
    "derive_chat_session_title",
    "extract_first_session_message_text",
    "extract_latest_session_message_text",
    "looks_like_session_identifier_title",
    "normalize_session_title",
    "normalize_title_state",
    "pick_title_focus_node",
    "sanitize_generated_title",
    "sanitize_session_title_text",
    "serialize_title_context_nodes",
    "should_schedule_title_generation",
    "slugify_session_name",
    "summarize_focus_node_for_title",
]
