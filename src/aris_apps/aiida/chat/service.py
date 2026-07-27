from __future__ import annotations

import asyncio
import copy
import json
import re
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from loguru import logger

from src.aris_apps.aiida.client import (
    build_bridge_context_headers,
    reset_bridge_call_listener,
    reset_bridge_request_headers,
    set_bridge_call_listener,
    set_bridge_request_headers,
)
from src.aris_apps.aiida.chat.batch_progress import (
    _batch_process_label,
    _classify_batch_process_status,
    _coerce_optional_int,
    _is_batch_process_node,
    _normalize_process_state_value,
    _summarize_chat_session_batch_progress,
)
from src.aris_apps.aiida.chat.context import (
    _build_user_message_payload,
    _coerce_positive_int,
    _looks_like_auto_environment_prompt_block,
    _normalize_focus_context_nodes,
    _normalize_session_parameters,
    _strip_auto_environment_prompt,
    normalize_context_node_ids,
)
from src.aris_apps.aiida.chat.group_gateway import (
    ChatGroupGateway,
    FrontendBridgeGroupGateway,
    build_project_group_label as _build_project_group_label,
    build_session_group_label as _build_session_group_label,
)
from src.aris_apps.aiida.chat.message_payloads import (
    _is_status_only_text,
    _merge_message_payload,
)
from src.aris_apps.aiida.chat.session_models import (
    MAX_CHAT_SESSION_MESSAGES as _MAX_CHAT_SESSION_MESSAGES,
    normalize_chat_messages as _normalize_chat_messages,
    normalize_chat_session_snapshot as _normalize_chat_session_snapshot,
    normalize_chat_session_tags as _normalize_chat_session_tags,
    serialize_chat_history,
    trim_text as _trim_text,
)
from src.aris_apps.aiida.chat.session_application_service import (
    SESSION_FIELD_UNSET,
    ChatSessionApplicationDependencies,
    ChatSessionApplicationService,
)
from src.aris_apps.aiida.chat.session_query_service import (
    ChatSessionQueryDependencies,
    ChatSessionQueryService,
)
from src.aris_apps.aiida.chat.session_repository import (
    CHAT_SESSIONS_KV_KEY as _CHAT_SESSIONS_KV_KEY,
    ChatSessionRepository,
    JsonChatSessionRepository,
)
from src.aris_apps.aiida.chat.submission_preview_service import (
    SubmissionPreviewRules,
    SubmissionPreviewService,
)
from src.aris_apps.aiida.chat.title_rules import (
    DEFAULT_SESSION_TITLE as _DEFAULT_SESSION_TITLE,
    TITLE_STAGE_CONTEXT_SWITCH as _TITLE_STAGE_CONTEXT_SWITCH,
    TITLE_STAGE_DEEP_SUMMARY as _TITLE_STAGE_DEEP_SUMMARY,
    TITLE_STAGE_INITIAL as _TITLE_STAGE_INITIAL,
    TITLE_STATE_FAILED as _TITLE_STATE_FAILED,
    TITLE_STATE_IDLE as _TITLE_STATE_IDLE,
    TITLE_STATE_PENDING as _TITLE_STATE_PENDING,
    TITLE_STATE_READY as _TITLE_STATE_READY,
    build_title_context_key as _build_title_context_key,
    build_title_generation_prompt as _build_title_generation_prompt,
    count_session_user_turns as _count_session_user_turns,
    derive_chat_session_title as _derive_chat_session_title,
    extract_first_session_message_text as _extract_first_session_message_text,
    extract_latest_session_message_text as _extract_latest_session_message_text,
    normalize_session_title as _normalize_session_title,
    normalize_title_state as _normalize_title_state,
    sanitize_generated_title as _sanitize_generated_title,
    sanitize_session_title_text as _sanitize_session_title_text,
    should_schedule_title_generation as _should_schedule_title_generation,
    slugify_session_name as _slugify_session_name,
)
from src.aris_apps.aiida.chat.workspace_manager import ChatWorkspaceManager
from src.aris_apps.aiida.domain.submissions import (
    submission_draft_is_batch as _domain_submission_draft_is_batch,
)
from src.aris_apps.aiida.presenters.workflow_view import enrich_submission_draft_payload
from src.aris_core.agent import AgentModelRejectedError, AgentRunRequest
from src.aris_core.config import settings
from src.aris_core.logging import log_event

_PENDING_SUBMISSION_KEY = "aiida_pending_submission"
_DEFAULT_PROJECT_NAME = "Default Project"
_MAX_CHAT_SESSIONS = 120
_KNOWN_PARALLEL_KEYS = {
    "num_machines",
    "num_mpiprocs_per_machine",
    "tot_num_mpiprocs",
    "num_cores_per_machine",
    "num_cores_per_mpiproc",
    "max_wallclock_seconds",
    "queue_name",
    "withmpi",
    "account",
    "qos",
    "npool",
    "nk",
    "ntg",
    "ndiag",
}
_CRITICAL_ADVANCED_KEYS = {
    "protocol",
    *_KNOWN_PARALLEL_KEYS,
}
_UNSET = object()
_SESSION_QUERY_SERVICE: ChatSessionQueryService | None = None
_SESSION_APPLICATION_SERVICE: ChatSessionApplicationService | None = None
_CHAT_SESSION_REPOSITORY = JsonChatSessionRepository(
    lambda: settings.ARIS_MEMORY_DIR,
)
_CHAT_WORKSPACE_MANAGER = ChatWorkspaceManager(
    lambda: settings.ARIS_PROJECTS_ROOT,
)
_CHAT_GROUP_GATEWAY: ChatGroupGateway = FrontendBridgeGroupGateway()
_managed_project_root = _CHAT_WORKSPACE_MANAGER.managed_project_root
_project_root_path = _CHAT_WORKSPACE_MANAGER.project_root_path
_get_session_slug = _CHAT_WORKSPACE_MANAGER.get_session_slug
_cleanup_project_workspace_dir = _CHAT_WORKSPACE_MANAGER.cleanup_project_workspace_dir
_normalize_project_root_path = _CHAT_WORKSPACE_MANAGER.normalize_project_root_path
_validate_new_project_root_path = _CHAT_WORKSPACE_MANAGER.validate_new_project_root_path
_project_default_environment_mode = (
    _CHAT_WORKSPACE_MANAGER.project_default_environment_mode
)
_resolve_workspace_target_path = (
    _CHAT_WORKSPACE_MANAGER.resolve_workspace_target_path
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_unique_session_slug(
    store: dict[str, Any],
    project_id: str,
    preferred_slug: str,
    *,
    session_id: str | None = None,
) -> str:
    base_slug = preferred_slug.strip() or "session"
    existing_slugs = {
        _get_session_slug(session)
        for session in store.get("sessions", [])
        if isinstance(session, dict)
        and str(session.get("project_id") or "").strip() == project_id
        and str(session.get("id") or "").strip() != str(session_id or "").strip()
    }

    if base_slug not in existing_slugs:
        return base_slug

    suffix = 2
    while True:
        candidate = f"{base_slug}-{suffix}"
        if candidate not in existing_slugs:
            return candidate
        suffix += 1


def _desired_session_slug(store: dict[str, Any], session: dict[str, Any], title: Any) -> str:
    project_id = str(session.get("project_id") or "").strip()
    title_slug = _slugify_session_name(title, fallback="new-conversation")
    return _resolve_unique_session_slug(store, project_id, title_slug, session_id=str(session.get("id") or ""))


def _get_chat_group_gateway(state: Any) -> ChatGroupGateway:
    gateway = getattr(state, "chat_group_gateway", None)
    if (
        callable(getattr(gateway, "inspect_group", None))
        and callable(getattr(gateway, "rename_group_label_if_available", None))
    ):
        return gateway
    return _CHAT_GROUP_GATEWAY


def _rename_session_group_label_if_needed(
    state: Any,
    store: dict[str, Any],
    session: dict[str, Any],
    old_slug: str | None,
) -> None:
    project = _get_store_project(store, str(session.get("project_id") or ""))
    project_name = str(project.get("name") or _DEFAULT_PROJECT_NAME)
    old_group_label = _build_session_group_label(project_name, old_slug or "session")
    new_group_label = _build_session_group_label(project_name, _get_session_slug(session))
    _get_chat_group_gateway(state).rename_group_label_if_available(
        old_group_label,
        new_group_label,
    )


def _build_chat_session_storage_payload(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(session.get("id") or "").strip(),
        "project_id": str(session.get("project_id") or "").strip(),
        "title": str(session.get("title") or _DEFAULT_SESSION_TITLE),
        "session_slug": _get_session_slug(session),
        "auto_title": bool(session.get("auto_title", False)),
        "title_state": _normalize_title_state(session.get("title_state")),
        "title_first_intent": str(session.get("title_first_intent") or "").strip() or None,
        "title_last_generated_turn": max(0, int(session.get("title_last_generated_turn") or 0)),
        "title_generation_count": max(0, int(session.get("title_generation_count") or 0)),
        "title_last_context_key": str(session.get("title_last_context_key") or "").strip() or None,
        "is_archived": bool(session.get("is_archived", False)),
        "created_at": str(session.get("created_at") or _now_iso()),
        "updated_at": str(session.get("updated_at") or _now_iso()),
        "tags": _normalize_chat_session_tags(session.get("tags")),
        "workspace_path": str(session.get("workspace_path") or "").strip() or None,
        "snapshot": _normalize_chat_session_snapshot(session.get("snapshot")),
        "messages": _normalize_chat_messages(session.get("messages")),
    }


def _build_chat_session_index_record(session: dict[str, Any]) -> dict[str, Any]:
    payload = _build_chat_session_storage_payload(session)
    payload.pop("messages", None)
    return payload


def _build_chat_session_store_index(store: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": max(0, int(store.get("version", 0) or 0)),
        "turn_seq": max(0, int(store.get("turn_seq", 0) or 0)),
        "active_project_id": store.get("active_project_id"),
        "active_session_id": store.get("active_session_id"),
        "projects": list(store.get("projects", [])),
        "sessions": [
            _build_chat_session_index_record(session)
            for session in store.get("sessions", [])
            if isinstance(session, dict)
        ],
    }


def _save_chat_session_store(
    repository: ChatSessionRepository,
    memory: Any,
    store: dict[str, Any],
) -> None:
    session_payloads: dict[str, dict[str, Any]] = {}
    for session in store.get("sessions", []):
        if not isinstance(session, dict):
            continue
        session_id = str(session.get("id") or "").strip()
        if not session_id:
            continue
        session_payloads[session_id] = _build_chat_session_storage_payload(session)
    repository.save(
        memory,
        index_payload=_build_chat_session_store_index(store),
        session_payloads=session_payloads,
    )


def _build_default_chat_project(project_id: str | None = None) -> dict[str, Any]:
    now = _now_iso()
    resolved_project_id = str(project_id or uuid4().hex).strip() or uuid4().hex
    return {
        "id": resolved_project_id,
        "name": _DEFAULT_PROJECT_NAME,
        "root_path": str(_managed_project_root(resolved_project_id)),
        "created_at": now,
        "updated_at": now,
    }


def _normalize_chat_project_record(raw_project: Any) -> dict[str, Any] | None:
    if not isinstance(raw_project, dict):
        return None

    project_id = str(raw_project.get("id") or "").strip()
    if not project_id:
        return None

    created_at = str(raw_project.get("created_at") or _now_iso())
    updated_at = str(raw_project.get("updated_at") or created_at)
    name = _trim_text(raw_project.get("name") or _DEFAULT_PROJECT_NAME, limit=80) or _DEFAULT_PROJECT_NAME
    return {
        "id": project_id,
        "name": name,
        "root_path": _normalize_project_root_path(raw_project.get("root_path"), project_id=project_id),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _normalize_chat_session_record(
    raw_session: Any,
    *,
    default_project_id: str,
    known_project_ids: set[str],
) -> dict[str, Any] | None:
    if not isinstance(raw_session, dict):
        return None

    session_id = str(raw_session.get("id") or "").strip()
    if not session_id:
        return None

    created_at = str(raw_session.get("created_at") or _now_iso())
    updated_at = str(raw_session.get("updated_at") or created_at)
    raw_title = _trim_text(raw_session.get("title") or _DEFAULT_SESSION_TITLE, limit=80) or _DEFAULT_SESSION_TITLE
    title = _normalize_session_title(raw_title)
    auto_title = bool(raw_session.get("auto_title", title == _DEFAULT_SESSION_TITLE))
    project_id = str(raw_session.get("project_id") or "").strip()
    if project_id not in known_project_ids:
        project_id = default_project_id

    try:
        title_last_generated_turn = max(0, int(raw_session.get("title_last_generated_turn") or 0))
    except (TypeError, ValueError):
        title_last_generated_turn = 0
    try:
        title_generation_count = max(0, int(raw_session.get("title_generation_count") or 0))
    except (TypeError, ValueError):
        title_generation_count = 0
    workspace_path = str(raw_session.get("workspace_path") or "").strip() or None
    session_slug = str(raw_session.get("session_slug") or "").strip()
    if not session_slug:
        title_slug = _slugify_session_name(title, fallback="")
        session_slug = title_slug or session_id

    return {
        "id": session_id,
        "project_id": project_id,
        "title": title,
        "session_slug": session_slug,
        "auto_title": auto_title,
        "title_state": _normalize_title_state(raw_session.get("title_state")),
        "title_first_intent": str(raw_session.get("title_first_intent") or "").strip() or None,
        "title_last_generated_turn": title_last_generated_turn,
        "title_generation_count": title_generation_count,
        "title_last_context_key": str(raw_session.get("title_last_context_key") or "").strip() or None,
        "is_archived": bool(raw_session.get("is_archived", False)),
        "created_at": created_at,
        "updated_at": updated_at,
        "tags": _normalize_chat_session_tags(raw_session.get("tags")),
        "workspace_path": workspace_path,
        "snapshot": _normalize_chat_session_snapshot(raw_session.get("snapshot")),
        "messages": _normalize_chat_messages(raw_session.get("messages")),
    }


def _project_map(store: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(project.get("id")): project
        for project in store.get("projects", [])
        if isinstance(project, dict) and str(project.get("id") or "").strip()
    }


def _get_store_project(store: dict[str, Any], project_id: str | None = None) -> dict[str, Any]:
    projects = _project_map(store)
    target_id = str(project_id or store.get("active_project_id") or "").strip()
    if target_id and target_id in projects:
        return projects[target_id]
    for project in store.get("projects", []):
        if isinstance(project, dict):
            return project
    fallback = _build_default_chat_project()
    store["projects"] = [fallback]
    store["active_project_id"] = fallback["id"]
    return fallback


def _find_store_project(store: dict[str, Any], project_id: str) -> dict[str, Any] | None:
    cleaned_project_id = str(project_id or "").strip()
    if not cleaned_project_id:
        return None
    return _project_map(store).get(cleaned_project_id)


def _ensure_project_workspace_dir(project: dict[str, Any]) -> Path:
    return _CHAT_WORKSPACE_MANAGER.ensure_project_workspace_dir(project)


def _ensure_session_workspace_dir(store: dict[str, Any], session: dict[str, Any]) -> str:
    project = _get_store_project(store, str(session.get("project_id") or ""))
    return _CHAT_WORKSPACE_MANAGER.ensure_session_workspace_dir(project, session)


def _ensure_store_workspace_dirs(store: dict[str, Any]) -> None:
    for project in store.get("projects", []):
        if isinstance(project, dict):
            _ensure_project_workspace_dir(project)
    for session in store.get("sessions", []):
        if isinstance(session, dict):
            _ensure_session_workspace_dir(store, session)


def _resolve_new_chat_session_project_id(
    store: dict[str, Any],
    requested_project_id: str | None = None,
) -> str:
    projects = _project_map(store)
    cleaned_requested = str(requested_project_id or "").strip()
    if cleaned_requested and cleaned_requested in projects:
        return cleaned_requested

    active_session_id = str(store.get("active_session_id") or "").strip()
    if active_session_id:
        active_session = next(
            (session for session in store.get("sessions", []) if isinstance(session, dict) and session.get("id") == active_session_id),
            None,
        )
        if isinstance(active_session, dict):
            candidate_project_id = str(active_session.get("project_id") or "").strip()
            if candidate_project_id in projects:
                return candidate_project_id

    active_project_id = str(store.get("active_project_id") or "").strip()
    if active_project_id in projects:
        return active_project_id

    return str(_get_store_project(store).get("id"))


def _normalize_chat_session_store(
    raw_store: Any,
    *,
    repository: ChatSessionRepository | None = None,
) -> dict[str, Any]:
    if not isinstance(raw_store, dict):
        raw_store = {}

    seen_project_ids: set[str] = set()
    projects: list[dict[str, Any]] = []
    for raw_project in raw_store.get("projects", []):
        project = _normalize_chat_project_record(raw_project)
        if project is None:
            continue
        project_id = str(project["id"])
        if project_id in seen_project_ids:
            continue
        seen_project_ids.add(project_id)
        projects.append(project)

    if not projects:
        projects.append(_build_default_chat_project())

    project_ids = {str(project["id"]) for project in projects}
    default_project_id = str(projects[0]["id"])

    seen_ids: set[str] = set()
    sessions: list[dict[str, Any]] = []
    for raw_session in raw_store.get("sessions", []):
        session_seed = raw_session if isinstance(raw_session, dict) else {}
        session_id = str(session_seed.get("id") or "").strip()
        merged_session = dict(session_seed)
        merged_session.pop("messages", None)
        if session_id:
            persisted_session = (repository or _CHAT_SESSION_REPOSITORY).load_session(session_id)
            if isinstance(persisted_session, dict):
                merged_session = {
                    **merged_session,
                    **persisted_session,
                }
        session = _normalize_chat_session_record(
            merged_session,
            default_project_id=default_project_id,
            known_project_ids=project_ids,
        )
        if session is None:
            continue
        session_id = str(session["id"])
        if session_id in seen_ids:
            continue
        seen_ids.add(session_id)
        sessions.append(session)
        if len(sessions) >= _MAX_CHAT_SESSIONS:
            break

    active_session_id = str(raw_store.get("active_session_id") or "").strip() or None
    active_session = next((session for session in sessions if session["id"] == active_session_id), None)
    if active_session is None or bool(active_session.get("is_archived", False)):
        active_session_id = next(
            (session["id"] for session in sessions if not bool(session.get("is_archived", False))),
            None,
        )

    active_project_id = str(raw_store.get("active_project_id") or "").strip() or None
    if active_session is None and active_session_id:
        active_session = next((session for session in sessions if session["id"] == active_session_id), None)
    if active_session is not None:
        session_project_id = str(active_session.get("project_id") or "").strip()
        if session_project_id in project_ids:
            active_project_id = session_project_id
    if active_project_id not in project_ids:
        active_project_id = default_project_id

    turn_seq = 0
    for session in sessions:
        for message in session["messages"]:
            turn_seq = max(turn_seq, int(message.get("turn_id") or 0))

    raw_turn_seq = raw_store.get("turn_seq")
    if isinstance(raw_turn_seq, int) and raw_turn_seq > turn_seq:
        turn_seq = raw_turn_seq

    raw_version = raw_store.get("version")
    version = int(raw_version) if isinstance(raw_version, int) else 0

    store = {
        "version": max(0, version),
        "turn_seq": max(0, turn_seq),
        "active_project_id": active_project_id,
        "active_session_id": active_session_id,
        "projects": projects,
        "sessions": sessions,
    }
    _ensure_store_workspace_dirs(store)
    return store


def _get_chat_session_store(state: Any) -> dict[str, Any]:
    store = getattr(state, "chat_session_store", None)
    if isinstance(store, dict):
        return store

    memory = getattr(state, "memory", None)
    repository = getattr(state, "chat_session_repository", _CHAT_SESSION_REPOSITORY)
    raw_store = repository.load_index(memory)

    store = _normalize_chat_session_store(raw_store, repository=repository)
    state.chat_session_store = store
    state.chat_sessions_version = int(store["version"])
    state.chat_turn_seq = max(int(getattr(state, "chat_turn_seq", 0)), int(store["turn_seq"]))
    state.active_chat_session_id = store["active_session_id"]
    state.active_chat_project_id = store["active_project_id"]
    _save_chat_session_store(repository, memory, store)
    if not hasattr(state, "chat_version"):
        state.chat_version = 0
    return store


def _persist_chat_session_store(state: Any) -> None:
    store = _get_chat_session_store(state)
    _ensure_store_workspace_dirs(store)
    state.chat_sessions_version = int(store["version"])
    state.chat_turn_seq = max(int(getattr(state, "chat_turn_seq", 0)), int(store["turn_seq"]))
    state.active_chat_session_id = store["active_session_id"]
    state.active_chat_project_id = store["active_project_id"]
    memory = getattr(state, "memory", None)
    repository = getattr(state, "chat_session_repository", _CHAT_SESSION_REPOSITORY)
    _save_chat_session_store(repository, memory, store)


def _touch_chat_sessions(state: Any) -> None:
    store = _get_chat_session_store(state)
    store["version"] = int(store.get("version", 0)) + 1
    state.chat_sessions_version = int(store["version"])


def _find_chat_session(
    state: Any,
    session_id: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    store = _get_chat_session_store(state)
    target_id = str(session_id or store.get("active_session_id") or "").strip()
    if not target_id:
        return None, store
    for session in store["sessions"]:
        if session["id"] == target_id:
            return session, store
    return None, store


def _build_chat_session_snapshot(
    metadata: dict[str, Any] | None,
    *,
    selected_model: str | None = None,
) -> dict[str, Any]:
    normalized_metadata = metadata if isinstance(metadata, dict) else {}
    selected_group_raw = (
        normalized_metadata.get("selected_group")
        or normalized_metadata.get("project_label")
        or normalized_metadata.get("group_label")
    )
    session_prompt_override_raw = normalized_metadata.get("session_prompt_override")
    if not isinstance(session_prompt_override_raw, str) or not session_prompt_override_raw.strip():
        session_prompt_override_raw = normalized_metadata.get("prompt_override")
    active_python_path = str(normalized_metadata.get("environment_active_python_path") or "").strip() or None
    if active_python_path is None:
        interpreter_info = normalized_metadata.get("interpreter_info")
        if isinstance(interpreter_info, Mapping):
            active_python_path = str(interpreter_info.get("python_path") or "").strip() or None
    snapshot = {
        "context_nodes": _normalize_focus_context_nodes(normalized_metadata.get("context_nodes")),
        "pinned_nodes": _normalize_focus_context_nodes(normalized_metadata.get("pinned_nodes")),
        "selected_group": str(selected_group_raw).strip() if isinstance(selected_group_raw, str) else None,
        "selected_model": str(selected_model).strip() if isinstance(selected_model, str) and selected_model.strip() else None,
        "session_environment": str(normalized_metadata.get("session_environment") or "").strip().lower() or None,
        "session_environment_auto": bool(normalized_metadata.get("session_environment_auto", True)),
        "environment_python_path": str(normalized_metadata.get("environment_python_path") or "").strip() or None,
        "environment_active_python_path": active_python_path,
        "prompt_override": _strip_auto_environment_prompt(session_prompt_override_raw) or None,
        "session_parameters": _normalize_session_parameters(normalized_metadata.get("session_parameters")),
    }
    return _normalize_chat_session_snapshot(snapshot)


def _serialize_chat_session_snapshot(session: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(session, dict):
        return _normalize_chat_session_snapshot({})
    return _normalize_chat_session_snapshot(session.get("snapshot"))


def _build_chat_session_preview(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        text = _trim_text(message.get("text") or "", limit=96)
        if text:
            return text
    return ""


def _serialize_chat_project_summary(project: dict[str, Any], store: dict[str, Any]) -> dict[str, Any]:
    project_id = str(project.get("id") or "")
    project_name = str(project.get("name") or _DEFAULT_PROJECT_NAME)
    project_sessions = [
        session
        for session in store.get("sessions", [])
        if isinstance(session, dict) and str(session.get("project_id") or "") == project_id
    ]
    latest_session_update = max(
        (
            str(session.get("updated_at") or session.get("created_at") or "")
            for session in project_sessions
            if isinstance(session, dict)
        ),
        default="",
    )
    return {
        "id": project_id,
        "name": project_name,
        "group_label": _build_project_group_label(project_name),
        "root_path": str(project.get("root_path") or ""),
        "created_at": str(project.get("created_at") or _now_iso()),
        "updated_at": max(str(project.get("updated_at") or _now_iso()), latest_session_update),
        "session_count": len(project_sessions),
        "active": str(store.get("active_project_id") or "") == project_id,
        "environment_mode_default": _project_default_environment_mode(project),
    }


def _serialize_chat_session_summary(session: dict[str, Any], store: dict[str, Any]) -> dict[str, Any]:
    snapshot = _serialize_chat_session_snapshot(session)
    messages = _normalize_chat_messages(session.get("messages"))
    project = _get_store_project(store, str(session.get("project_id") or ""))
    workspace_path = _ensure_session_workspace_dir(store, session)
    project_name = str(project.get("name") or _DEFAULT_PROJECT_NAME)
    project_group_label = _build_project_group_label(project_name)
    return {
        "id": session["id"],
        "project_id": str(session.get("project_id") or project.get("id") or ""),
        "title": str(session.get("title") or _DEFAULT_SESSION_TITLE),
        "session_slug": _get_session_slug(session),
        "auto_title": bool(session.get("auto_title", False)),
        "title_state": _normalize_title_state(session.get("title_state")),
        "is_archived": bool(session.get("is_archived", False)),
        "created_at": str(session.get("created_at") or _now_iso()),
        "updated_at": str(session.get("updated_at") or _now_iso()),
        "tags": _normalize_chat_session_tags(session.get("tags")),
        "project_label": project_name,
        "project_group_label": project_group_label,
        "session_group_label": _build_session_group_label(project_name, _get_session_slug(session)),
        "workspace_path": workspace_path,
        "node_count": len(snapshot.get("context_nodes") or []),
        "preview": _build_chat_session_preview(messages),
        "message_count": len(messages),
        "snapshot": snapshot,
    }


def _serialize_chat_session_detail(session: dict[str, Any], store: dict[str, Any], state: Any | None = None) -> dict[str, Any]:
    detail = _serialize_chat_session_summary(session, store)
    detail["version"] = int(getattr(state, "chat_version", 0)) if state is not None else 0
    detail["messages"] = serialize_chat_history(_normalize_chat_messages(session.get("messages")))
    return detail


def _get_session_query_service() -> ChatSessionQueryService:
    global _SESSION_QUERY_SERVICE
    if _SESSION_QUERY_SERVICE is None:
        _SESSION_QUERY_SERVICE = ChatSessionQueryService(
            ChatSessionQueryDependencies(
                get_store=_get_chat_session_store,
                find_session=_find_chat_session,
                serialize_project=_serialize_chat_project_summary,
                serialize_session=_serialize_chat_session_summary,
                serialize_session_detail=_serialize_chat_session_detail,
                serialize_snapshot=_serialize_chat_session_snapshot,
                serialize_history=serialize_chat_history,
            )
        )
    return _SESSION_QUERY_SERVICE


def _get_session_application_service() -> ChatSessionApplicationService:
    global _SESSION_APPLICATION_SERVICE
    if _SESSION_APPLICATION_SERVICE is None:
        _SESSION_APPLICATION_SERVICE = ChatSessionApplicationService(
            ChatSessionApplicationDependencies(
                get_store=_get_chat_session_store,
                find_session=_find_chat_session,
                trim_text=_trim_text,
                sanitize_title=_sanitize_session_title_text,
                normalize_tags=_normalize_chat_session_tags,
                normalize_snapshot=_normalize_chat_session_snapshot,
                normalize_identifier_list=_normalize_identifier_list,
                validate_project_root=_validate_new_project_root_path,
                ensure_project_workspace=_ensure_project_workspace_dir,
                ensure_session_workspace=_ensure_session_workspace_dir,
                cleanup_project_workspace=_cleanup_project_workspace_dir,
                resolve_project_id=_resolve_new_chat_session_project_id,
                resolve_session_slug=_resolve_unique_session_slug,
                desired_session_slug=_desired_session_slug,
                slugify_session_name=_slugify_session_name,
                get_session_slug=_get_session_slug,
                rename_session_group=_rename_session_group_label_if_needed,
                serialize_project=_serialize_chat_project_summary,
                serialize_session_detail=_serialize_chat_session_detail,
                reconcile_active_targets=_reconcile_active_chat_targets,
                persist_store=_persist_chat_session_store,
                touch_sessions=_touch_chat_sessions,
                touch_chat=touch_chat,
                get_active_session_id=get_active_chat_session_id,
                now_iso=_now_iso,
                default_session_title=_DEFAULT_SESSION_TITLE,
                title_state_ready=_TITLE_STATE_READY,
                title_state_idle=_TITLE_STATE_IDLE,
                max_sessions=_MAX_CHAT_SESSIONS,
            )
        )
    return _SESSION_APPLICATION_SERVICE


def list_chat_projects(state: Any) -> list[dict[str, Any]]:
    return _get_session_query_service().list_projects(state)


def list_chat_sessions(state: Any) -> list[dict[str, Any]]:
    return _get_session_query_service().list_sessions(state)


def get_active_chat_project_id(state: Any) -> str | None:
    return _get_session_query_service().get_active_project_id(state)


def get_active_chat_session_id(state: Any) -> str | None:
    return _get_session_query_service().get_active_session_id(state)


def get_chat_session_detail(state: Any, session_id: str) -> dict[str, Any] | None:
    return _get_session_query_service().get_session_detail(state, session_id)


def get_chat_session_batch_progress(state: Any, session_id: str) -> dict[str, Any] | None:
    session, store = _find_chat_session(state, session_id)
    if session is None:
        return None

    project = _get_store_project(store, str(session.get("project_id") or ""))
    project_name = str(project.get("name") or _DEFAULT_PROJECT_NAME)
    session_group_label = _build_session_group_label(project_name, _get_session_slug(session))
    group_payload = _get_chat_group_gateway(state).inspect_group(
        session_group_label,
        limit=500,
    )
    if not isinstance(group_payload, dict):
        return None

    raw_nodes = group_payload.get("nodes")
    nodes = raw_nodes if isinstance(raw_nodes, list) else []
    return _summarize_chat_session_batch_progress(
        session_id=str(session.get("id") or session_id),
        title=str(session.get("title") or _DEFAULT_SESSION_TITLE),
        session_group_label=session_group_label,
        nodes=[entry for entry in nodes if isinstance(entry, dict)],
    )


def get_chat_session_workspace_path(state: Any, session_id: str | None = None) -> str | None:
    session, store = _find_chat_session(state, session_id)
    if session is None:
        return None
    return _ensure_session_workspace_dir(store, session)


def get_chat_session_project_root_path(state: Any, session_id: str | None = None) -> str | None:
    session, store = _find_chat_session(state, session_id)
    if session is None:
        return None
    project = _get_store_project(store, str(session.get("project_id") or ""))
    return str(_ensure_project_workspace_dir(project))


def describe_chat_project_file(
    state: Any,
    project_id: str,
    *,
    relative_path: str,
) -> dict[str, Any] | None:
    _session, store = _find_chat_session(state, None)
    project = _find_store_project(store, project_id)
    if project is None:
        return None

    workspace_root = _ensure_project_workspace_dir(project)
    target = _resolve_workspace_target_path(workspace_root, relative_path=relative_path)
    if target == workspace_root:
        raise ValueError("Project file path must point to a file")
    if not target.exists():
        raise ValueError("Requested project file does not exist")
    if target.is_dir():
        raise ValueError("Requested project file path points to a directory")

    return {
        "project_id": str(project.get("id") or ""),
        "project_name": str(project.get("name") or _DEFAULT_PROJECT_NAME),
        "workspace_path": str(workspace_root),
        "path": str(target),
        "relative_path": str(target.relative_to(workspace_root)),
    }


def build_chat_project_worker_headers(state: Any, project_id: str) -> dict[str, str] | None:
    _session, store = _find_chat_session(state, None)
    project = _find_store_project(store, project_id)
    if project is None:
        return None

    workspace_path = str(_ensure_project_workspace_dir(project))
    return build_bridge_context_headers(
        workspace_path=workspace_path,
        project_id=project.get("id"),
    )


def _build_worker_workspace_headers(state: Any, session_id: str | None = None) -> dict[str, str] | None:
    session, store = _find_chat_session(state, session_id)
    if session is None:
        return None
    project = _get_store_project(store, str(session.get("project_id") or ""))
    _ensure_session_workspace_dir(store, session)
    workspace_path = str(_ensure_project_workspace_dir(project))
    snapshot = _normalize_chat_session_snapshot(session.get("snapshot"))
    return build_bridge_context_headers(
        workspace_path=workspace_path,
        session_id=session.get("id"),
        project_id=project.get("id"),
        python_path=snapshot.get("environment_python_path") or snapshot.get("environment_active_python_path"),
    )


def list_chat_session_workspace_files(
    state: Any,
    session_id: str,
    *,
    relative_path: str | None = None,
) -> dict[str, Any] | None:
    session, store = _find_chat_session(state, session_id)
    if session is None:
        return None

    project = _get_store_project(store, str(session.get("project_id") or ""))
    workspace_root = Path(_ensure_session_workspace_dir(store, session))
    target = _resolve_workspace_target_path(workspace_root, relative_path=relative_path)
    if target.exists() and not target.is_dir():
        raise ValueError("Requested workspace path is a file")
    target.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    for child in sorted(target.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower()))[:200]:
        stat = child.stat()
        entries.append(
            {
                "name": child.name,
                "path": str(child),
                "relative_path": str(child.relative_to(workspace_root)),
                "is_dir": child.is_dir(),
                "size": None if child.is_dir() else int(stat.st_size),
                "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )

    return {
        "session_id": str(session["id"]),
        "project_id": str(project.get("id") or ""),
        "project_name": str(project.get("name") or _DEFAULT_PROJECT_NAME),
        "workspace_path": str(workspace_root),
        "relative_path": str(target.relative_to(workspace_root)) if target != workspace_root else "",
        "entries": entries,
    }


def list_chat_project_workspace_files(
    state: Any,
    project_id: str,
    *,
    relative_path: str | None = None,
) -> dict[str, Any] | None:
    _session, store = _find_chat_session(state, None)
    project = _get_store_project(store, project_id)
    if project is None:
        return None

    workspace_root = _ensure_project_workspace_dir(project)
    target = _resolve_workspace_target_path(workspace_root, relative_path=relative_path)
    if target.exists() and not target.is_dir():
        raise ValueError("Requested workspace path is a file")
    target.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    for child in sorted(target.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower()))[:200]:
        stat = child.stat()
        entries.append(
            {
                "name": child.name,
                "path": str(child),
                "relative_path": str(child.relative_to(workspace_root)),
                "is_dir": child.is_dir(),
                "size": None if child.is_dir() else int(stat.st_size),
                "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )

    return {
        "project_id": str(project.get("id") or ""),
        "project_name": str(project.get("name") or _DEFAULT_PROJECT_NAME),
        "workspace_path": str(workspace_root),
        "relative_path": str(target.relative_to(workspace_root)) if target != workspace_root else "",
        "entries": entries,
    }


def write_chat_project_file(
    state: Any,
    project_id: str,
    *,
    relative_path: str,
    content: str,
    overwrite: bool = True,
) -> dict[str, Any] | None:
    _session, store = _find_chat_session(state, None)
    project = _find_store_project(store, project_id)
    if project is None:
        return None

    workspace_root = _ensure_project_workspace_dir(project)
    target = _resolve_workspace_target_path(workspace_root, relative_path=relative_path)
    if target == workspace_root:
        raise ValueError("Project file path must point to a file")
    if target.exists() and target.is_dir():
        raise ValueError("Project file path points to a directory")
    if target.exists() and not overwrite:
        raise FileExistsError(f"Project file already exists: {target.name}")

    target.parent.mkdir(parents=True, exist_ok=True)
    created = not target.exists()
    target.write_text(str(content), encoding="utf-8")

    updated_at = _now_iso()
    project["updated_at"] = updated_at
    _touch_chat_sessions(state)
    _persist_chat_session_store(state)

    directory_path = "" if target.parent == workspace_root else str(target.parent.relative_to(workspace_root))
    return {
        "project_id": str(project.get("id") or ""),
        "project_name": str(project.get("name") or _DEFAULT_PROJECT_NAME),
        "workspace_path": str(workspace_root),
        "path": str(target),
        "relative_path": str(target.relative_to(workspace_root)),
        "directory_path": directory_path,
        "filename": target.name,
        "size": int(target.stat().st_size),
        "updated_at": updated_at,
        "created": created,
    }


def get_chat_snapshot(state: Any) -> dict[str, Any]:
    return _get_session_query_service().get_snapshot(state)


def archive_chat_session(state: Any, session_id: str) -> dict[str, Any] | None:
    return _get_session_application_service().archive_session(
        state,
        session_id,
    )


def create_chat_project(
    state: Any,
    *,
    name: str,
    root_path: str | None = None,
    activate: bool = True,
) -> dict[str, Any]:
    return _get_session_application_service().create_project(
        state,
        name=name,
        root_path=root_path,
        activate=activate,
    )


def create_chat_session(
    state: Any,
    *,
    title: str | None = None,
    snapshot: dict[str, Any] | None = None,
    activate: bool = True,
    archive_session_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    return _get_session_application_service().create_session(
        state,
        title=title,
        snapshot=snapshot,
        activate=activate,
        archive_session_id=archive_session_id,
        project_id=project_id,
    )


def activate_chat_session(state: Any, session_id: str) -> dict[str, Any] | None:
    return _get_session_application_service().activate_session(
        state,
        session_id,
    )


def update_chat_session(
    state: Any,
    session_id: str,
    *,
    title: str | object = _UNSET,
    tags: list[str] | object = _UNSET,
    snapshot: dict[str, Any] | object = _UNSET,
) -> dict[str, Any] | None:
    return _get_session_application_service().update_session(
        state,
        session_id,
        title=SESSION_FIELD_UNSET if title is _UNSET else title,
        tags=SESSION_FIELD_UNSET if tags is _UNSET else tags,
        snapshot=SESSION_FIELD_UNSET if snapshot is _UNSET else snapshot,
    )


def _normalize_identifier_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _reconcile_active_chat_targets(state: Any, store: dict[str, Any]) -> None:
    project_ids = {
        str(project.get("id") or "").strip()
        for project in store.get("projects", [])
        if isinstance(project, dict) and str(project.get("id") or "").strip()
    }
    sessions = [
        session
        for session in store.get("sessions", [])
        if isinstance(session, dict)
    ]
    sessions_by_recent = sorted(
        sessions,
        key=lambda session: str(session.get("updated_at") or session.get("created_at") or ""),
        reverse=True,
    )

    active_session_id = str(store.get("active_session_id") or "").strip()
    active_session = next(
        (
            session
            for session in sessions_by_recent
            if session.get("id") == active_session_id and not bool(session.get("is_archived", False))
        ),
        None,
    )
    if active_session is None:
        active_session = next(
            (session for session in sessions_by_recent if not bool(session.get("is_archived", False))),
            None,
        )
    store["active_session_id"] = str(active_session.get("id") or "") if isinstance(active_session, dict) else None

    if isinstance(active_session, dict):
        active_project_id = str(active_session.get("project_id") or "").strip()
        store["active_project_id"] = active_project_id if active_project_id in project_ids else None
    else:
        current_project_id = str(store.get("active_project_id") or "").strip()
        if current_project_id in project_ids:
            store["active_project_id"] = current_project_id
        else:
            projects_by_recent = sorted(
                (
                    project
                    for project in store.get("projects", [])
                    if isinstance(project, dict) and str(project.get("id") or "").strip()
                ),
                key=lambda project: max(
                    str(project.get("updated_at") or project.get("created_at") or ""),
                    max(
                        (
                            str(session.get("updated_at") or session.get("created_at") or "")
                            for session in sessions
                            if str(session.get("project_id") or "").strip() == str(project.get("id") or "").strip()
                        ),
                        default="",
                    ),
                ),
                reverse=True,
            )
            store["active_project_id"] = (
                str(projects_by_recent[0].get("id") or "").strip()
                if projects_by_recent
                else None
            )

    state.active_chat_session_id = store.get("active_session_id")
    state.active_chat_project_id = store.get("active_project_id")


def delete_chat_items(
    state: Any,
    *,
    project_ids: list[str] | None = None,
    session_ids: list[str] | None = None,
) -> dict[str, list[str]]:
    return _get_session_application_service().delete_items(
        state,
        project_ids=project_ids,
        session_ids=session_ids,
    )


def get_chat_history(state: Any, session_id: str | None = None) -> list[dict[str, Any]]:
    return _get_session_query_service().get_history(state, session_id)


def touch_chat(state: Any) -> None:
    state.chat_version = getattr(state, "chat_version", 0) + 1


def _ensure_chat_lock(state: Any) -> asyncio.Lock:
    lock = getattr(state, "chat_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        state.chat_lock = lock
    return lock


def _ensure_chat_task_registry(state: Any) -> dict[int, asyncio.Task]:
    tasks = getattr(state, "chat_turn_tasks", None)
    if tasks is None:
        tasks = {}
        state.chat_turn_tasks = tasks
    return tasks


def _update_assistant_message(
    state: Any,
    turn_id: int,
    text: str | None,
    status: str = "thinking",
    *,
    session_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    chat_history = get_chat_history(state, session_id=session_id)
    for msg in reversed(chat_history):
        if msg.get("role") == "assistant" and msg.get("turn_id") == turn_id:
            previous_text = str(msg.get("text") or "")
            if text is None:
                next_text = previous_text
            else:
                incoming_text = str(text)
                if incoming_text.strip() and previous_text.strip():
                    if _is_status_only_text(incoming_text) and not _is_status_only_text(previous_text):
                        next_text = previous_text
                    else:
                        next_text = incoming_text
                elif not incoming_text.strip() and previous_text.strip():
                    next_text = previous_text
                else:
                    next_text = incoming_text

            msg["text"] = next_text
            msg["status"] = status
            if isinstance(payload, dict):
                merged_payload = _merge_message_payload(
                    msg.get("payload") if isinstance(msg.get("payload"), dict) else None,
                    payload,
                )
                if isinstance(merged_payload, dict):
                    msg["payload"] = merged_payload
            touch_chat(state)
            return
    logger.warning(log_event("aiida.chat_turn.message_update_missed", turn_id=turn_id, status=status))


def _extract_submission_inputs(draft: dict[str, Any]) -> dict[str, Any]:
    request_wrapper_keys = {
        "workchain",
        "workchain_label",
        "workchain_entry_point",
        "entry_point",
        "structure_pk",
        "code",
        "protocol",
        "overrides",
    }
    visited: set[int] = set()

    def unwrap(node: Any, depth: int = 0) -> dict[str, Any] | None:
        if not isinstance(node, dict) or depth > 8:
            return None
        marker = id(node)
        if marker in visited:
            return None
        visited.add(marker)

        direct_inputs = node.get("inputs")
        if isinstance(direct_inputs, dict):
            nested_inputs = unwrap(direct_inputs, depth + 1)
            return nested_inputs if isinstance(nested_inputs, dict) else direct_inputs

        builder_inputs = node.get("builder_inputs")
        if isinstance(builder_inputs, dict):
            nested_builder_inputs = unwrap(builder_inputs, depth + 1)
            return nested_builder_inputs if isinstance(nested_builder_inputs, dict) else builder_inputs

        for key in ("builder", "draft", "submission", "payload", "result"):
            nested = node.get(key)
            if not isinstance(nested, dict):
                continue
            extracted = unwrap(nested, depth + 1)
            if isinstance(extracted, dict):
                return extracted

        has_wrapper_markers = any(key in node for key in request_wrapper_keys)
        if has_wrapper_markers:
            namespace_like = any(
                isinstance(value, dict) and key not in request_wrapper_keys
                for key, value in node.items()
            )
            if not namespace_like:
                return None

        return node

    extracted = unwrap(draft)
    return extracted if isinstance(extracted, dict) else {}


def _find_first_named_value(payload: Any, candidate_keys: set[str]) -> Any:
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).strip().lower()
            if lowered in candidate_keys and value not in (None, "", []):
                return value
            nested = _find_first_named_value(value, candidate_keys)
            if nested is not None:
                return nested
    elif isinstance(payload, list):
        for item in payload:
            nested = _find_first_named_value(item, candidate_keys)
            if nested is not None:
                return nested
    return None


def _looks_like_code_key(key: Any) -> bool:
    lowered = str(key).strip().lower()
    return lowered in {"code", "code_label", "codes"} or lowered.endswith("_code")


def _find_first_matching_value(payload: Any, predicate: Any) -> Any:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if predicate(str(key), value) and value not in (None, "", [], {}):
                return value
            nested = _find_first_matching_value(value, predicate)
            if nested is not None:
                return nested
    elif isinstance(payload, list):
        for item in payload:
            nested = _find_first_matching_value(item, predicate)
            if nested is not None:
                return nested
    return None


def _is_node_metadata_envelope(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    lowered_keys = {str(key).strip().lower() for key in value.keys() if str(key).strip()}
    if not lowered_keys:
        return False
    if {"pk", "uuid"} & lowered_keys:
        return True
    if "type" in lowered_keys and "value" in lowered_keys:
        return True
    return bool({"node_type", "full_type"} & lowered_keys)


def _coerce_node_envelope_value(value: dict[str, Any]) -> Any:
    for candidate_key in ("value", "payload", "label", "name", "full_label", "code", "family"):
        if candidate_key not in value:
            continue
        candidate = value.get(candidate_key)
        if candidate is None:
            continue
        if isinstance(candidate, str) and not candidate.strip():
            continue
        return candidate
    return value


def _flatten_input_values(payload: Any, *, prefix: str = "", out: dict[str, Any] | None = None) -> dict[str, Any]:
    flattened = out if isinstance(out, dict) else {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key).strip()
            if not key_text:
                continue
            path = f"{prefix}.{key_text}" if prefix else key_text
            if _is_node_metadata_envelope(value):
                flattened[path] = _coerce_node_envelope_value(value)
                continue
            if isinstance(value, dict):
                _flatten_input_values(value, prefix=path, out=flattened)
                continue
            flattened[path] = value
        return flattened
    if prefix:
        flattened[prefix] = payload
    return flattened


def _extract_target_computer(draft: dict[str, Any]) -> str | None:
    value = _find_first_named_value(
        draft,
        {"computer", "computer_label", "computer_name", "target_computer"},
    )
    if isinstance(value, dict):
        for key in ("label", "name", "computer_label", "computer_name"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
        pk = _coerce_positive_int(value.get("pk"))
        return f"PK #{pk}" if pk else None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _extract_process_label(draft: dict[str, Any]) -> str:
    value = _find_first_named_value(
        draft,
        {
            "process_label",
            "workchain",
            "workchain_label",
            "entry_point",
            "workflow",
            "workflow_label",
        },
    )
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            return cleaned
    return "AiiDA Workflow"


def _extract_parallel_settings(draft: dict[str, Any]) -> dict[str, Any]:
    settings: dict[str, Any] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                lowered = str(key).strip().lower()
                if lowered in _KNOWN_PARALLEL_KEYS and lowered not in settings:
                    settings[lowered] = value
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(draft)
    return settings


def _is_empty_submission_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _normalize_primary_input_field(label: str, value: Any) -> dict[str, Any] | None:
    if _is_empty_submission_value(value):
        return None

    field: dict[str, Any] = {"label": label}
    if isinstance(value, dict):
        pk = _coerce_positive_int(value.get("pk") or value.get("structure_pk") or value.get("code_pk"))
        display: str | None = None
        for key in ("label", "name", "value", "formula", "code_label", "family"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                display = candidate.strip()
                break
        if display is None and pk is not None:
            display = f"PK #{pk}"
        if display is None:
            display = json.dumps(value, ensure_ascii=False)
        field["value"] = display
        if pk is not None:
            field["pk"] = pk
        return field

    if isinstance(value, list):
        preview = ", ".join(str(item) for item in value[:4])
        suffix = " ..." if len(value) > 4 else ""
        field["value"] = preview + suffix
        return field

    scalar_pk = _coerce_positive_int(value)
    if scalar_pk is not None and label.lower() == "structure":
        field["value"] = f"PK #{scalar_pk}"
        field["pk"] = scalar_pk
        return field

    field["value"] = str(value)
    return field


def _extract_primary_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    primary_inputs: dict[str, Any] = {}

    code_value = _find_first_matching_value(
        inputs,
        lambda key, _value: _looks_like_code_key(key),
    )
    code_field = _normalize_primary_input_field("Code", code_value)
    if isinstance(code_field, dict):
        primary_inputs["code"] = code_field

    structure_value = _find_first_named_value(
        inputs,
        {"structure", "structure_pk", "structure_id"},
    )
    structure_field = _normalize_primary_input_field("Structure", structure_value)
    if isinstance(structure_field, dict):
        primary_inputs["structure"] = structure_field

    pseudos_value = _find_first_named_value(
        inputs,
        {"pseudos", "pseudo", "pseudopotentials", "pseudo_family", "pseudo_family_label"},
    )
    pseudos_field = _normalize_primary_input_field("Pseudopotentials", pseudos_value)
    if isinstance(pseudos_field, dict):
        primary_inputs["pseudos"] = pseudos_field

    return primary_inputs


def _is_default_advanced_setting(key: str, value: Any) -> bool:
    lowered = key.strip().lower()
    if lowered in {
        "num_machines",
        "num_mpiprocs_per_machine",
        "tot_num_mpiprocs",
        "num_cores_per_machine",
        "num_cores_per_mpiproc",
        "npool",
        "nk",
        "ntg",
        "ndiag",
    }:
        parsed = _coerce_positive_int(value)
        return parsed == 1
    if lowered == "withmpi":
        return value is True
    if lowered == "protocol":
        return str(value).strip().lower() in {"default", "moderate"}
    return False


def _should_include_advanced_setting(path: str, value: Any) -> bool:
    if _is_empty_submission_value(value):
        return False
    if _is_node_metadata_envelope(value):
        return _coerce_node_envelope_value(value) is not value and not _is_empty_submission_value(_coerce_node_envelope_value(value))
    lowered_path = str(path).strip().lower()
    if not lowered_path or lowered_path.startswith("metadata."):
        return False
    segments = [segment for segment in lowered_path.split(".") if segment]
    if not segments:
        return False
    leaf = segments[-1]
    if leaf in {"pk", "uuid"}:
        return False
    if any(_looks_like_code_key(segment) for segment in segments):
        return False
    if any(
        segment in {"structure", "structure_pk", "structure_id", "computer", "computer_label", "computer_name"}
        for segment in segments
    ):
        return False
    if leaf in {"process_label", "workchain", "workchain_label", "entry_point", "workflow", "workflow_label"}:
        return False
    return not _is_default_advanced_setting(leaf, value)


def _collect_advanced_settings(payload: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    for path, value in _flatten_input_values(payload).items():
        lowered_path = str(path).strip().lower()
        if not _should_include_advanced_setting(lowered_path, value):
            continue
        leaf = lowered_path.rsplit(".", 1)[-1]
        target_key = leaf if leaf and leaf not in settings else lowered_path
        if target_key in settings:
            continue
        settings[target_key] = value
    return settings


def _normalize_recommended_inputs(
    raw_recommended: Any,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    source = raw_recommended if isinstance(raw_recommended, dict) else fallback
    normalized: dict[str, Any] = {}
    for key, value in source.items():
        normalized_key = str(key).strip().lower()
        if not normalized_key:
            continue
        if _is_empty_submission_value(value) or _is_default_advanced_setting(normalized_key, value):
            continue
        normalized[normalized_key] = value
    return normalized


def _collect_pk_map(payload: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    explicit_pk_list_keys = {"input_pks", "node_pks", "structure_pks"}

    def append_entry(pk: int, path: str, label: str) -> None:
        dedupe_key = (pk, path)
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        entries.append({"pk": pk, "path": path, "label": label})

    def walk(node: Any, path: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_text = str(key)
                lowered = key_text.strip().lower()
                key_path = f"{path}.{key_text}" if path else key_text
                if lowered == "pk" or lowered.endswith("_pk"):
                    candidate = _coerce_positive_int(value)
                    if candidate is not None:
                        append_entry(candidate, key_path, key_text)
                elif lowered in explicit_pk_list_keys and isinstance(value, list):
                    for index, item in enumerate(value):
                        candidate = _coerce_positive_int(item)
                        if candidate is None:
                            continue
                        append_entry(candidate, f"{key_path}[{index}]", key_text)

                if isinstance(value, (dict, list)):
                    walk(value, key_path)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                item_path = f"{path}[{index}]" if path else f"[{index}]"
                walk(item, item_path)

    walk(payload)
    return entries[:120]


def _submission_draft_is_batch(submission_draft: dict[str, Any] | None) -> bool:
    return _domain_submission_draft_is_batch(submission_draft)


def _extract_actionable_submission_draft(
    raw_submission_draft: dict[str, Any],
    *,
    inputs: dict[str, Any],
    meta: dict[str, Any],
    process_label: str,
    draft: dict[str, Any] | list[dict[str, Any]] | None,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    if isinstance(draft, dict):
        return copy.deepcopy(draft)
    if isinstance(draft, list):
        normalized_batch = [copy.deepcopy(item) for item in draft if isinstance(item, dict)]
        if normalized_batch:
            return normalized_batch

    raw_meta_draft = meta.get("draft")
    if isinstance(raw_meta_draft, dict):
        return copy.deepcopy(raw_meta_draft)
    if isinstance(raw_meta_draft, list):
        normalized_meta_batch = [copy.deepcopy(item) for item in raw_meta_draft if isinstance(item, dict)]
        if normalized_meta_batch:
            return normalized_meta_batch

    for key in ("jobs", "tasks", "submissions", "drafts"):
        candidate = raw_submission_draft.get(key)
        if not isinstance(candidate, list):
            continue
        normalized_candidate = [copy.deepcopy(item) for item in candidate if isinstance(item, dict)]
        if normalized_candidate:
            return normalized_candidate

    entry_point_candidates = (
        meta.get("entry_point"),
        meta.get("workchain"),
        raw_submission_draft.get("entry_point"),
        raw_submission_draft.get("workchain"),
        process_label,
    )
    for candidate in entry_point_candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        if "." not in text and ":" not in text:
            continue
        if not isinstance(inputs, dict) or not inputs:
            return None
        return {
            "entry_point": text,
            "inputs": copy.deepcopy(inputs),
        }

    return None


def _build_submission_preview_overview(
    submission_draft: dict[str, Any],
    *,
    preferred_mode: str | None = None,
) -> dict[str, Any]:
    meta = submission_draft.get("meta") if isinstance(submission_draft.get("meta"), dict) else {}
    batch_aggregation = (
        submission_draft.get("batch_aggregation")
        if isinstance(submission_draft.get("batch_aggregation"), dict)
        else meta.get("batch_aggregation")
        if isinstance(meta.get("batch_aggregation"), dict)
        else {}
    )
    raw_draft = meta.get("draft")
    raw_job_count = _coerce_positive_int(meta.get("job_count"))
    job_count = raw_job_count
    if job_count is None and isinstance(raw_draft, list):
        job_count = len([item for item in raw_draft if isinstance(item, dict)]) or None
    if job_count is None and isinstance(batch_aggregation.get("items"), list):
        job_count = len([item for item in batch_aggregation["items"] if isinstance(item, dict)]) or None
    if job_count is None and isinstance(meta.get("structure_pks"), list):
        job_count = len([item for item in meta["structure_pks"] if _coerce_positive_int(item) is not None]) or None

    varying_paths: list[str] = []
    raw_variable_paths = batch_aggregation.get("variable_paths")
    if isinstance(raw_variable_paths, list):
        varying_paths = [
            str(path).strip()
            for path in raw_variable_paths
            if isinstance(path, str) and str(path).strip()
        ]
    if not varying_paths and isinstance(batch_aggregation.get("items"), list):
        seen_varying: set[str] = set()
        for item in batch_aggregation["items"]:
            diff = item.get("diff") if isinstance(item, dict) and isinstance(item.get("diff"), dict) else {}
            for path in _flatten_input_values(diff).keys():
                cleaned = str(path).strip()
                if cleaned:
                    seen_varying.add(cleaned)
        varying_paths = sorted(seen_varying)

    common_inputs = (
        batch_aggregation.get("common")
        if isinstance(batch_aggregation.get("common"), dict)
        else submission_draft.get("inputs")
        if isinstance(submission_draft.get("inputs"), dict)
        else {}
    )
    shared_paths = [path for path in sorted(_flatten_input_values(common_inputs).keys()) if str(path).strip()]

    mode = preferred_mode if preferred_mode in {"single", "batch"} else None
    if mode is None:
        mode = "batch" if _submission_draft_is_batch(submission_draft) else "single"
    if mode == "single" and job_count and job_count > 1:
        mode = "batch"

    return {
        "mode": mode,
        "job_count": job_count or 1,
        "shared_paths": shared_paths,
        "varying_paths": varying_paths,
        "shared_count": len(shared_paths),
        "varying_count": len(varying_paths),
    }


def _apply_submission_preview_overview(
    submission_draft: dict[str, Any],
    *,
    preferred_mode: str | None = None,
) -> dict[str, Any]:
    meta = submission_draft.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        submission_draft["meta"] = meta
    overview = _build_submission_preview_overview(submission_draft, preferred_mode=preferred_mode)
    meta["preview_mode"] = overview["mode"]
    meta["preview_overview"] = overview
    return submission_draft


def _normalize_submission_draft_payload(
    raw_submission_draft: dict[str, Any],
    *,
    draft: dict[str, Any] | list[dict[str, Any]] | None,
    validation: dict[str, Any] | None,
    validation_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    process_label_raw = raw_submission_draft.get("process_label")
    process_label = process_label_raw.strip() if isinstance(process_label_raw, str) and process_label_raw.strip() else None
    if process_label is None and isinstance(draft, dict):
        process_label = _extract_process_label(draft)
    if process_label is None:
        process_label = "AiiDA Workflow"

    inputs = raw_submission_draft.get("inputs")
    if not isinstance(inputs, dict):
        inputs = _extract_submission_inputs(draft) if isinstance(draft, dict) else {}
    primary_inputs = raw_submission_draft.get("primary_inputs")
    if not isinstance(primary_inputs, dict):
        primary_inputs = _extract_primary_inputs(inputs)

    raw_advanced_settings = raw_submission_draft.get("advanced_settings")
    advanced_settings: dict[str, Any]
    if isinstance(raw_advanced_settings, dict):
        advanced_settings = {}
        for key, value in raw_advanced_settings.items():
            lowered = str(key).strip().lower()
            if _is_empty_submission_value(value) or _is_default_advanced_setting(lowered, value):
                continue
            advanced_settings[lowered] = value
    else:
        advanced_settings = _collect_advanced_settings(inputs)

    raw_meta = raw_submission_draft.get("meta")
    meta: dict[str, Any] = dict(raw_meta) if isinstance(raw_meta, dict) else {}
    raw_all_inputs = raw_submission_draft.get("all_inputs")
    if not isinstance(raw_all_inputs, dict):
        meta_all_inputs = meta.get("all_inputs")
        raw_all_inputs = meta_all_inputs if isinstance(meta_all_inputs, dict) else None
    raw_input_groups = raw_submission_draft.get("input_groups")
    if not isinstance(raw_input_groups, list):
        meta_input_groups = meta.get("input_groups")
        raw_input_groups = meta_input_groups if isinstance(meta_input_groups, list) else None
    raw_recommended_inputs = raw_submission_draft.get("recommended_inputs")
    if not isinstance(raw_recommended_inputs, dict):
        meta_recommended = meta.get("recommended_inputs")
        raw_recommended_inputs = meta_recommended if isinstance(meta_recommended, dict) else None
    recommended_inputs = _normalize_recommended_inputs(raw_recommended_inputs, advanced_settings)
    meta["recommended_inputs"] = recommended_inputs
    raw_pk_map = meta.get("pk_map")
    if isinstance(raw_pk_map, list):
        normalized_pk_map: list[dict[str, Any]] = []
        seen: set[tuple[int, str]] = set()
        for item in raw_pk_map:
            if not isinstance(item, dict):
                continue
            pk = _coerce_positive_int(item.get("pk"))
            if pk is None:
                continue
            path_value = item.get("path")
            path = str(path_value).strip() if isinstance(path_value, str) and path_value.strip() else f"pk_{pk}"
            dedupe_key = (pk, path)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized_pk_map.append(
                {
                    "pk": pk,
                    "path": path,
                    "label": str(item.get("label") or "pk"),
                }
            )
        meta["pk_map"] = normalized_pk_map
    else:
        meta["pk_map"] = _collect_pk_map(inputs)

    actionable_draft = _extract_actionable_submission_draft(
        raw_submission_draft,
        inputs=inputs,
        meta=meta,
        process_label=process_label,
        draft=draft,
    )
    if actionable_draft is not None:
        meta["draft"] = actionable_draft
    draft_record = actionable_draft if isinstance(actionable_draft, dict) else None
    if isinstance(draft_record, dict):
        meta.setdefault("target_computer", _extract_target_computer(draft_record))
        meta.setdefault("parallel_settings", _extract_parallel_settings(draft_record))
    parallel_settings = meta.get("parallel_settings")
    if not isinstance(parallel_settings, dict):
        parallel_settings = _extract_parallel_settings(draft_record) if isinstance(draft_record, dict) else {}
    meta["parallel_settings"] = parallel_settings
    if "target_computer" not in meta:
        meta["target_computer"] = _extract_target_computer(draft_record) if isinstance(draft_record, dict) else None
    meta.setdefault("workchain", process_label)
    for key, value in parallel_settings.items():
        lowered = str(key).strip().lower()
        if lowered in advanced_settings:
            continue
        if _is_empty_submission_value(value) or _is_default_advanced_setting(lowered, value):
            continue
        advanced_settings[lowered] = value
    if isinstance(validation, dict):
        meta["validation"] = validation
    if isinstance(validation_summary, dict):
        meta["validation_summary"] = validation_summary

    payload = {
        "process_label": process_label,
        "inputs": inputs,
        "primary_inputs": primary_inputs,
        "recommended_inputs": recommended_inputs,
        "advanced_settings": advanced_settings,
        "meta": meta,
    }
    raw_batch_aggregation = raw_submission_draft.get("batch_aggregation")
    if isinstance(raw_batch_aggregation, dict):
        payload["batch_aggregation"] = raw_batch_aggregation
    if isinstance(raw_all_inputs, dict):
        payload["all_inputs"] = raw_all_inputs
    if isinstance(raw_input_groups, list):
        payload["input_groups"] = raw_input_groups
    return _apply_submission_preview_overview(enrich_submission_draft_payload(payload))


def _build_submission_draft_payload(
    draft: dict[str, Any],
    *,
    validation: dict[str, Any] | None,
    validation_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    inputs = _extract_submission_inputs(draft)
    advanced_settings = _collect_advanced_settings(inputs)
    parallel_settings = _extract_parallel_settings(draft)
    for key, value in parallel_settings.items():
        if key in advanced_settings:
            continue
        if _is_empty_submission_value(value) or _is_default_advanced_setting(key, value):
            continue
        advanced_settings[key] = value
    recommended_inputs = _normalize_recommended_inputs(None, advanced_settings)
    process_label = _extract_process_label(draft)
    meta: dict[str, Any] = {
        "pk_map": _collect_pk_map(inputs),
        "target_computer": _extract_target_computer(draft),
        "parallel_settings": parallel_settings,
        "draft": draft,
        "recommended_inputs": recommended_inputs,
        "workchain": process_label,
    }
    if isinstance(validation, dict):
        meta["validation"] = validation
    if isinstance(validation_summary, dict):
        meta["validation_summary"] = validation_summary
    payload = {
        "process_label": process_label,
        "inputs": inputs,
        "primary_inputs": _extract_primary_inputs(inputs),
        "recommended_inputs": recommended_inputs,
        "advanced_settings": advanced_settings,
        "meta": meta,
    }
    return _apply_submission_preview_overview(enrich_submission_draft_payload(payload))


_submission_preview_service = SubmissionPreviewService(
    SubmissionPreviewRules(
        normalize_draft=lambda raw: _normalize_submission_draft_payload(
            raw,
            draft=None,
            validation=None,
            validation_summary=None,
        ),
        apply_overview=_apply_submission_preview_overview,
        is_batch_draft=_submission_draft_is_batch,
    )
)


def _append_assistant_message(
    state: Any,
    turn_id: int,
    text: str,
    status: str = "done",
    *,
    session_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    chat_history = get_chat_history(state, session_id=session_id)
    message = {
        "role": "assistant",
        "text": text,
        "status": status,
        "turn_id": turn_id,
    }
    if isinstance(payload, dict):
        message["payload"] = payload
    chat_history.append(message)
    touch_chat(state)
    logger.info(
        log_event(
            "aiida.chat_turn.message_append",
            turn_id=turn_id,
            status=status,
            chars=len(text),
            has_payload=bool(payload),
        )
    )


def _generate_session_title_sync(prompt: str, model_name: str) -> str:
    api_key = str(getattr(settings, "GEMINI_API_KEY", "") or "").strip()
    if not api_key or api_key == "your-key-here":
        raise RuntimeError("Gemini API key not configured for title generation.")

    resolved_model_name = str(model_name or "").strip() or str(getattr(settings, "DEFAULT_MODEL", "") or "").strip()
    if ":" in resolved_model_name:
        resolved_model_name = resolved_model_name.split(":", 1)[1].strip()
    if not resolved_model_name:
        raise RuntimeError("No model available for title generation.")

    from google import genai

    client = genai.Client(
        api_key=api_key,
        http_options={"api_version": settings.GEMINI_API_VERSION},
    )
    response = client.models.generate_content(
        model=resolved_model_name,
        contents=prompt,
    )
    return str(getattr(response, "text", "") or "").strip()


def _ensure_chat_title_task_registry(state: Any) -> dict[str, asyncio.Task]:
    tasks = getattr(state, "chat_title_tasks", None)
    if tasks is None:
        tasks = {}
        state.chat_title_tasks = tasks
    return tasks


def _finalize_auto_title_update(
    state: Any,
    session: dict[str, Any],
    *,
    title: str,
    completed_turn_id: int,
    context_key: str,
    title_state: str,
) -> None:
    session["title"] = title or _DEFAULT_SESSION_TITLE
    store = _get_chat_session_store(state)
    old_slug = _get_session_slug(session)
    session["session_slug"] = _desired_session_slug(store, session, session["title"])
    session["title_state"] = _normalize_title_state(title_state)
    session["title_last_generated_turn"] = max(0, int(completed_turn_id))
    session["title_generation_count"] = max(0, int(session.get("title_generation_count") or 0)) + 1
    session["title_last_context_key"] = context_key or None
    session["updated_at"] = _now_iso()
    _ensure_session_workspace_dir(store, session)
    _rename_session_group_label_if_needed(state, store, session, old_slug)
    _touch_chat_sessions(state)
    _persist_chat_session_store(state)


async def _run_session_title_generation(
    state: Any,
    *,
    session_id: str,
    selected_model: str,
    completed_turn_id: int,
    stage: str,
    prompt: str,
    fallback_title: str,
    context_key: str,
) -> None:
    try:
        generated_title = await asyncio.to_thread(_generate_session_title_sync, prompt, selected_model)
        resolved_title = _sanitize_generated_title(generated_title, fallback_title)
        title_state = _TITLE_STATE_READY if resolved_title else _TITLE_STATE_FAILED
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001
        logger.warning(
            log_event(
                "aiida.chat_title_generation.failed",
                session_id=session_id,
                turn_id=completed_turn_id,
                stage=stage,
                model=selected_model,
                error=str(error),
            )
        )
        resolved_title = fallback_title
        title_state = _TITLE_STATE_READY if resolved_title != _DEFAULT_SESSION_TITLE else _TITLE_STATE_FAILED

    lock = _ensure_chat_lock(state)
    async with lock:
        session, _store = _find_chat_session(state, session_id)
        if session is None:
            return
        if not bool(session.get("auto_title", False)):
            return
        if _normalize_title_state(session.get("title_state")) != _TITLE_STATE_PENDING:
            return
        _finalize_auto_title_update(
            state,
            session,
            title=resolved_title or _DEFAULT_SESSION_TITLE,
            completed_turn_id=completed_turn_id,
            context_key=context_key,
            title_state=title_state,
        )
        logger.info(
            log_event(
                "aiida.chat_title_generation.done",
                session_id=session_id,
                turn_id=completed_turn_id,
                stage=stage,
                title=session.get("title"),
            )
        )


def _schedule_session_title_generation(
    state: Any,
    *,
    session_id: str,
    selected_model: str,
    completed_turn_id: int,
    stage: str,
) -> None:
    session, _store = _find_chat_session(state, session_id)
    if session is None or not bool(session.get("auto_title", False)):
        return

    existing_task = _ensure_chat_title_task_registry(state).get(session_id)
    if existing_task is not None and not existing_task.done():
        return

    prompt = _build_title_generation_prompt(session, stage=stage, completed_turn_id=completed_turn_id)
    fallback_seed = _extract_latest_session_message_text(session, "user") or str(session.get("title_first_intent") or "")
    fallback_title = _sanitize_generated_title(
        _derive_chat_session_title(fallback_seed, session.get("snapshot")),
        _DEFAULT_SESSION_TITLE,
    )
    context_key = _build_title_context_key(session.get("snapshot"))
    session["title_state"] = _TITLE_STATE_PENDING
    session["updated_at"] = _now_iso()
    _touch_chat_sessions(state)
    _persist_chat_session_store(state)

    task = asyncio.create_task(
        _run_session_title_generation(
            state,
            session_id=session_id,
            selected_model=selected_model,
            completed_turn_id=completed_turn_id,
            stage=stage,
            prompt=prompt,
            fallback_title=fallback_title,
            context_key=context_key,
        )
    )
    _ensure_chat_title_task_registry(state)[session_id] = task
    task.add_done_callback(
        lambda _task, _state=state, _session_id=session_id: _ensure_chat_title_task_registry(_state).pop(_session_id, None)
    )


def _merge_context_node_ids(
    context_node_ids: list[int] | None,
    metadata: dict[str, Any] | None,
) -> list[int]:
    raw_ids: list[Any] = []
    if context_node_ids:
        raw_ids.extend(context_node_ids)
    if isinstance(metadata, dict):
        raw_ids.extend(normalize_context_node_ids(metadata.get("context_pks")))
        raw_ids.extend(normalize_context_node_ids(metadata.get("context_node_pks")))
    return normalize_context_node_ids(raw_ids)


def _inject_context_priority_instruction(user_intent: str, context_pks: list[int]) -> str:
    if not context_pks:
        return user_intent
    serialized = ", ".join(str(pk) for pk in context_pks)
    return (
        "PRIMARY TURN CONTEXT:\n"
        f"- context_pks: [{serialized}]\n"
        "- Treat these PKs as the primary subjects of the current user query.\n"
        "- If the request is ambiguous, prioritize inspecting these nodes first.\n\n"
        f"USER REQUEST:\n{user_intent}"
    )


def _inject_session_preference_instruction(user_intent: str, metadata: dict[str, Any] | None) -> str:
    normalized_metadata = metadata if isinstance(metadata, dict) else {}
    session_environment = str(normalized_metadata.get("session_environment") or "").strip().lower()
    prompt_override = str(normalized_metadata.get("prompt_override") or "").strip()
    session_parameters = _normalize_session_parameters(normalized_metadata.get("session_parameters"))
    pinned_nodes = _normalize_focus_context_nodes(normalized_metadata.get("pinned_nodes"))

    preference_lines: list[str] = []
    if session_environment:
        preference_lines.append(f"- active_environment: {session_environment}")
    if pinned_nodes:
        serialized_nodes = ", ".join(f"#{item['pk']}" for item in pinned_nodes)
        preference_lines.append(f"- pinned_nodes: [{serialized_nodes}]")
    if session_parameters:
        serialized_params = ", ".join(f"{item['key']}={item['value']}" for item in session_parameters)
        preference_lines.append(f"- session_parameters: {serialized_params}")
    if prompt_override:
        preference_lines.append(f"- prompt_override: {prompt_override}")

    if not preference_lines:
        return user_intent

    return (
        "SESSION PREFERENCES:\n"
        + "\n".join(preference_lines)
        + "\n- Treat these preferences as defaults for this session unless the current message overrides them.\n\n"
        + f"USER REQUEST:\n{user_intent}"
    )


async def _thinking_status_ticker(
    state: Any,
    turn_id: int,
    session_id: str,
    stop_event: asyncio.Event,
    get_running_tools: Callable[[], list[str]] | None = None,
    get_step_history: Callable[[], list[str]] | None = None,
) -> None:
    started = time.perf_counter()
    dots = 0
    while not stop_event.is_set():
        elapsed = int(time.perf_counter() - started)
        dots = (dots % 3) + 1
        status_lines = [f"Thinking: waiting for model response ({elapsed}s){'.' * dots}"]
        running_tools: list[str] = []
        if callable(get_running_tools):
            running_tools = get_running_tools()
            if running_tools:
                status_lines.extend(f"Running: {tool_name}..." for tool_name in running_tools[-5:])
        step_history: list[str] = []
        if callable(get_step_history):
            step_history = get_step_history()

        status_payload = {
            "type": "status",
            "tool_calls": running_tools[-20:],
            "status": {
                "current_step": step_history[-1] if step_history else (running_tools[-1] if running_tools else None),
                "steps": step_history[-40:],
                "elapsed_seconds": elapsed,
            },
        }
        _update_assistant_message(
            state,
            turn_id,
            "\n".join(status_lines),
            status="thinking",
            session_id=session_id,
            payload=status_payload,
        )
        await asyncio.sleep(0.9)


def cancel_chat_turn(state: Any, turn_id: int | None = None) -> int | None:
    tasks = _ensure_chat_task_registry(state)
    if turn_id is not None:
        candidates = [(turn_id, tasks.get(turn_id))]
    else:
        candidates = sorted(tasks.items(), key=lambda item: item[0], reverse=True)

    for candidate_turn_id, task in candidates:
        if task is None:
            continue
        if task.done():
            tasks.pop(candidate_turn_id, None)
            continue
        task.cancel()
        session_id = getattr(task, "session_id", None)
        _update_assistant_message(
            state,
            candidate_turn_id,
            "Response stopped by user.",
            status="error",
            session_id=str(session_id) if isinstance(session_id, str) and session_id else None,
        )
        logger.info(log_event("aiida.chat_turn.cancel.requested", turn_id=candidate_turn_id))
        return candidate_turn_id

    return None


def start_chat_turn(
    state: Any,
    *,
    user_intent: str,
    selected_model: str,
    fetch_context_nodes: Callable[[list[int]], list[dict[str, Any]]],
    context_archive: str | None = None,
    context_node_ids: list[int] | None = None,
    metadata: dict[str, Any] | None = None,
    source: str = "frontend",
) -> int:
    normalized_metadata = dict(metadata or {})
    normalized_node_ids = _merge_context_node_ids(context_node_ids, normalized_metadata)
    normalized_metadata["context_pks"] = normalized_node_ids
    normalized_metadata["context_node_pks"] = normalized_node_ids
    session, store = _find_chat_session(state, None)
    if session is None:
        session_detail = create_chat_session(
            state,
            snapshot=_build_chat_session_snapshot(normalized_metadata, selected_model=selected_model),
            activate=True,
        )
        session, store = _find_chat_session(state, session_detail["id"])
    if session is None:
        raise RuntimeError("Unable to initialize chat session.")

    session["snapshot"] = _build_chat_session_snapshot(normalized_metadata, selected_model=selected_model)
    if not str(session.get("title_first_intent") or "").strip():
        session["title_first_intent"] = user_intent
    session["updated_at"] = _now_iso()

    turn_id = int(store.get("turn_seq", 0)) + 1
    store["turn_seq"] = turn_id
    state.chat_turn_seq = turn_id
    session_id = str(session["id"])
    chat_history = session["messages"]

    user_message: dict[str, Any] = {"role": "user", "text": user_intent, "turn_id": turn_id}
    user_payload = _build_user_message_payload(normalized_metadata, normalized_node_ids)
    if isinstance(user_payload, dict):
        user_message["payload"] = user_payload
    chat_history.append(user_message)
    chat_history.append(
        {
            "role": "assistant",
            "text": "Thinking: request queued.",
            "status": "thinking",
            "turn_id": turn_id,
            "payload": {
                "type": "status",
                "status": {
                    "current_step": "Queued request",
                    "steps": [],
                },
                "tool_calls": [],
            },
        }
    )
    session["messages"] = chat_history[-_MAX_CHAT_SESSION_MESSAGES:]
    touch_chat(state)
    _touch_chat_sessions(state)
    _persist_chat_session_store(state)

    logger.info(
        log_event(
            "aiida.chat_turn.queued",
            turn_id=turn_id,
            session_id=session_id,
            source=source,
            model=selected_model,
            intent=user_intent[:120],
            context=context_archive,
            context_node_ids=",".join(str(pk) for pk in normalized_node_ids) or None,
            metadata_keys=",".join(sorted(str(key) for key in normalized_metadata.keys())) or None,
        )
    )

    task = asyncio.create_task(
        _execute_chat_turn(
            state=state,
            turn_id=turn_id,
            session_id=session_id,
            user_intent=user_intent,
            selected_model=selected_model,
            fetch_context_nodes=fetch_context_nodes,
            context_archive=context_archive,
            context_node_ids=normalized_node_ids,
            metadata=normalized_metadata,
        )
    )
    setattr(task, "session_id", session_id)
    _ensure_chat_task_registry(state)[turn_id] = task
    task.add_done_callback(
        lambda _task, _state=state, _turn_id=turn_id: _ensure_chat_task_registry(_state).pop(_turn_id, None)
    )
    return turn_id


async def _execute_chat_turn(
    state: Any,
    turn_id: int,
    session_id: str,
    user_intent: str,
    selected_model: str,
    fetch_context_nodes: Callable[[list[int]], list[dict[str, Any]]],
    context_archive: str | None = None,
    context_node_ids: list[int] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    agent_runtime = getattr(state, "agent_runtime", None)
    deps_class = getattr(state, "deps_class", None)
    lock = _ensure_chat_lock(state)
    t0 = time.perf_counter()
    spinner_stop = asyncio.Event()
    spinner_task: asyncio.Task | None = None
    bridge_tool_calls: list[str] = []

    def _record_bridge_call(tool_name: str) -> None:
        cleaned = str(tool_name).strip()
        if not cleaned:
            return
        if bridge_tool_calls and bridge_tool_calls[-1] == cleaned:
            return
        bridge_tool_calls.append(cleaned)
        if len(bridge_tool_calls) > 40:
            del bridge_tool_calls[:-40]

    async with lock:
        logger.info(
            log_event(
                "aiida.chat_turn.start",
                turn_id=turn_id,
                model=selected_model,
                intent=user_intent[:120],
                context=context_archive,
                context_node_ids=",".join(str(pk) for pk in normalize_context_node_ids(context_node_ids)) or None,
                metadata_keys=",".join(sorted(str(key) for key in (metadata or {}).keys())) or None,
            )
        )

        try:
            if agent_runtime is None or deps_class is None:
                raise RuntimeError("Agent dependencies are not ready")

            normalized_node_ids = _merge_context_node_ids(context_node_ids, metadata)
            context_nodes = fetch_context_nodes(normalized_node_ids)
            if context_nodes:
                _update_assistant_message(
                    state,
                    turn_id,
                    f"Thinking: loaded {len(context_nodes)} referenced nodes...",
                    status="thinking",
                    session_id=session_id,
                )

            deps_kwargs: dict[str, Any] = {
                "archive_path": context_archive,
                "memory": getattr(state, "memory", None),
            }
            if "session_id" in getattr(deps_class, "__annotations__", {}):
                deps_kwargs["session_id"] = session_id
            if "app_state" in getattr(deps_class, "__annotations__", {}):
                deps_kwargs["app_state"] = state
            if "context_nodes" in getattr(deps_class, "__annotations__", {}):
                deps_kwargs["context_nodes"] = context_nodes
            current_deps = deps_class(**deps_kwargs)
            step_history: list[str] = getattr(current_deps, "step_history", [])

            def _record_step_update(step_text: str) -> None:
                cleaned = str(step_text).strip()
                if not cleaned:
                    return
                payload = {
                    "type": "status",
                    "tool_calls": bridge_tool_calls[-20:],
                    "status": {
                        "current_step": cleaned,
                        "steps": step_history[-40:],
                    },
                }
                _update_assistant_message(
                    state,
                    turn_id,
                    None,
                    status="thinking",
                    session_id=session_id,
                    payload=payload,
                )

            if hasattr(current_deps, "step_callback"):
                setattr(current_deps, "step_callback", _record_step_update)

            listener_token = set_bridge_call_listener(_record_bridge_call)
            request_headers_token = set_bridge_request_headers(_build_worker_workspace_headers(state, session_id))
            spinner_task = asyncio.create_task(
                _thinking_status_ticker(
                    state=state,
                    turn_id=turn_id,
                    session_id=session_id,
                    stop_event=spinner_stop,
                    get_running_tools=lambda: list(bridge_tool_calls),
                    get_step_history=lambda: list(step_history),
                )
            )
            try:
                run_intent = _inject_session_preference_instruction(user_intent, metadata)
                run_intent = _inject_context_priority_instruction(run_intent, normalized_node_ids)
                retry_policy = agent_runtime.retry_policy
                retry_budget = retry_policy.unavailable_retries
                retry_base_backoff_seconds = retry_policy.base_backoff_seconds
                last_run_error: Exception | None = None
                result = None
                for attempt in range(retry_budget + 1):
                    try:
                        result = await agent_runtime.run(
                            AgentRunRequest(
                                prompt=run_intent,
                                deps=current_deps,
                                model_name=selected_model,
                                metadata={
                                    "session_id": session_id,
                                    "turn_id": turn_id,
                                },
                            )
                        )
                        last_run_error = None
                        break
                    except asyncio.CancelledError:
                        raise
                    except AgentModelRejectedError as run_error:
                        logger.error(
                            log_event(
                                "aiida.chat_turn.model_rejected",
                                turn_id=turn_id,
                                model=selected_model,
                                provider=run_error.provider,
                                error=str(run_error)[:500],
                            )
                        )
                        raise RuntimeError(str(run_error)) from run_error
                    except Exception as run_error:  # noqa: BLE001
                        error_text = str(run_error)
                        is_retryable = agent_runtime.is_retryable_unavailable_error(run_error)
                        if is_retryable and attempt < retry_budget:
                            wait_seconds = retry_base_backoff_seconds * (2**attempt)
                            retry_step = (
                                "The model provider is temporarily unavailable. "
                                f"Auto-retrying in {wait_seconds:.1f}s ({attempt + 1}/{retry_budget})."
                            )
                            current_deps.log_step(retry_step)
                            logger.warning(
                                log_event(
                                    "aiida.chat_turn.model_unavailable_retry",
                                    turn_id=turn_id,
                                    model=selected_model,
                                    attempt=attempt + 1,
                                    max_attempts=retry_budget + 1,
                                    wait_seconds=f"{wait_seconds:.2f}",
                                    error=error_text[:500],
                                )
                            )
                            await asyncio.sleep(wait_seconds)
                            continue

                        last_run_error = run_error
                        break

                if result is None:
                    if last_run_error is None:
                        raise RuntimeError("Model call failed: no result and no error captured.")
                    retry_exhausted = agent_runtime.is_retryable_unavailable_error(
                        last_run_error
                    )
                    if retry_exhausted:
                        logger.error(
                            log_event(
                                "aiida.chat_turn.model_unavailable_retry_exhausted",
                                turn_id=turn_id,
                                model=selected_model,
                                attempts=retry_budget + 1,
                                error=str(last_run_error)[:500],
                            )
                        )
                    raise last_run_error
            finally:
                reset_bridge_call_listener(listener_token)
                reset_bridge_request_headers(request_headers_token)

            spinner_stop.set()
            if spinner_task:
                spinner_task.cancel()
                with suppress(asyncio.CancelledError):
                    await spinner_task
                spinner_task = None

            elapsed = time.perf_counter() - t0
            output = getattr(result, "output", None)
            if output is None:
                raise RuntimeError("Agent returned no output payload")

            if hasattr(current_deps, "step_history") and hasattr(output, "thought_process"):
                output.thought_process = current_deps.step_history

            answer_text = str(output.answer) if hasattr(output, "answer") else str(output)
            output_task_mode = _submission_preview_service.normalize_task_mode(
                getattr(output, "task_mode", None)
            )
            structured_submission_request = getattr(output, "submission_request", None)
            raw_output_payload = getattr(output, "data_payload", None)
            existing_submission_draft = (
                _submission_preview_service.extract_submission_draft(
                    raw_output_payload
                )
                if isinstance(raw_output_payload, dict)
                else None
            )
            auto_prepared_payload = None
            if (
                output_task_mode in {"single", "batch"}
                and existing_submission_draft is None
            ):
                auto_prepared_payload = await _submission_preview_service.prepare_request(
                    structured_submission_request,
                    current_deps,
                    bridge_tool_calls,
                )
            if isinstance(auto_prepared_payload, dict):
                merged_output_payload = (
                    dict(raw_output_payload)
                    if isinstance(raw_output_payload, dict)
                    else {}
                )
                merged_output_payload.update(auto_prepared_payload)
                if hasattr(output, "data_payload"):
                    output.data_payload = merged_output_payload
            message_payload = _submission_preview_service.build_message_payload(
                output,
                tool_calls=bridge_tool_calls,
                task_mode=output_task_mode,
            )
            if isinstance(message_payload, dict) and not isinstance(
                message_payload.get("submission_draft"), dict
            ):
                recovery_plan = message_payload.get("recovery_plan")
                next_step = message_payload.get("next_step")
                canonical_blocker_text = (
                    _submission_preview_service.render_blocker_message(
                        task_mode=output_task_mode,
                        recovery_plan=(
                            recovery_plan
                            if isinstance(recovery_plan, dict)
                            else None
                        ),
                        next_step=next_step if isinstance(next_step, str) else None,
                    )
                )
                if canonical_blocker_text:
                    answer_text = canonical_blocker_text
            _append_assistant_message(
                state,
                turn_id,
                answer_text,
                status="done",
                session_id=session_id,
                payload=message_payload,
            )
            session_history = get_chat_history(state, session_id=session_id)
            session_history[:] = session_history[-_MAX_CHAT_SESSION_MESSAGES:]
            session, _store = _find_chat_session(state, session_id)
            if session is not None:
                session["updated_at"] = _now_iso()
            touch_chat(state)
            _touch_chat_sessions(state)
            _persist_chat_session_store(state)
            logger.info(
                log_event(
                    "aiida.chat_turn.done",
                    turn_id=turn_id,
                    session_id=session_id,
                    run_id=getattr(result, "run_id", None),
                    elapsed=f"{elapsed:.2f}s",
                    answer_chars=len(answer_text),
                    steps=len(getattr(current_deps, "step_history", []) or []),
                )
            )

            session_for_title, _ = _find_chat_session(state, session_id)
            if session_for_title is not None:
                title_stage = _should_schedule_title_generation(session_for_title, turn_id)
                if title_stage:
                    _schedule_session_title_generation(
                        state,
                        session_id=session_id,
                        selected_model=selected_model,
                        completed_turn_id=turn_id,
                        stage=title_stage,
                    )

            if hasattr(state, "memory") and state.memory:
                try:
                    turn_metadata: dict[str, Any] = {
                        "context_archive": context_archive,
                        "context_node_ids": normalized_node_ids,
                    }
                    for key, value in (metadata or {}).items():
                        turn_metadata[str(key)] = value
                    state.memory.add_turn(
                        intent=user_intent,
                        response=answer_text,
                        metadata=turn_metadata,
                    )
                except Exception as mem_error:  # noqa: BLE001
                    logger.warning(
                        log_event(
                            "aiida.chat_turn.persist_failed",
                            turn_id=turn_id,
                            error=str(mem_error),
                        )
                    )

        except asyncio.CancelledError:
            elapsed = time.perf_counter() - t0
            _update_assistant_message(
                state,
                turn_id,
                "Response stopped by user.",
                status="error",
                session_id=session_id,
            )
            session_history = get_chat_history(state, session_id=session_id)
            session_history[:] = session_history[-_MAX_CHAT_SESSION_MESSAGES:]
            session, _store = _find_chat_session(state, session_id)
            if session is not None:
                session["updated_at"] = _now_iso()
            touch_chat(state)
            _touch_chat_sessions(state)
            _persist_chat_session_store(state)
            logger.info(
                log_event(
                    "aiida.chat_turn.cancelled",
                    turn_id=turn_id,
                    session_id=session_id,
                    elapsed=f"{elapsed:.2f}s",
                    model=selected_model,
                )
            )
            raise
        except Exception as error:  # noqa: BLE001
            elapsed = time.perf_counter() - t0
            logger.exception(
                log_event(
                    "aiida.chat_turn.failed",
                    turn_id=turn_id,
                    elapsed=f"{elapsed:.2f}s",
                    model=selected_model,
                    error=str(error),
                )
            )
            _append_assistant_message(
                state,
                turn_id,
                f"Request failed: {error}",
                status="error",
                session_id=session_id,
            )
            session_history = get_chat_history(state, session_id=session_id)
            session_history[:] = session_history[-_MAX_CHAT_SESSION_MESSAGES:]
            session, _store = _find_chat_session(state, session_id)
            if session is not None:
                session["updated_at"] = _now_iso()
            touch_chat(state)
            _touch_chat_sessions(state)
            _persist_chat_session_store(state)
        finally:
            spinner_stop.set()
            if spinner_task:
                spinner_task.cancel()
                with suppress(asyncio.CancelledError):
                    await spinner_task
