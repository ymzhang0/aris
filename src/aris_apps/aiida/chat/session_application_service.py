"""Write-side application service for chat projects and sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

SESSION_FIELD_UNSET = object()


@dataclass(frozen=True)
class ChatSessionApplicationDependencies:
    """Domain and persistence operations needed by session commands."""

    get_store: Callable[[Any], dict[str, Any]]
    find_session: Callable[
        [Any, str | None],
        tuple[dict[str, Any] | None, dict[str, Any]],
    ]
    trim_text: Callable[..., str]
    sanitize_title: Callable[[Any], str]
    normalize_tags: Callable[[Any], list[str]]
    normalize_snapshot: Callable[[Any], dict[str, Any]]
    normalize_identifier_list: Callable[[Any], list[str]]
    validate_project_root: Callable[..., str]
    ensure_project_workspace: Callable[[dict[str, Any]], Any]
    ensure_session_workspace: Callable[
        [dict[str, Any], dict[str, Any]],
        str,
    ]
    cleanup_project_workspace: Callable[[dict[str, Any]], None]
    resolve_project_id: Callable[..., str]
    resolve_session_slug: Callable[..., str]
    desired_session_slug: Callable[..., str]
    slugify_session_name: Callable[..., str]
    get_session_slug: Callable[[dict[str, Any]], str]
    rename_session_group: Callable[..., None]
    serialize_project: Callable[
        [dict[str, Any], dict[str, Any]],
        dict[str, Any],
    ]
    serialize_session_detail: Callable[
        [dict[str, Any], dict[str, Any], Any | None],
        dict[str, Any],
    ]
    reconcile_active_targets: Callable[[Any, dict[str, Any]], None]
    persist_store: Callable[..., None]
    touch_sessions: Callable[[Any], None]
    touch_chat: Callable[[Any], None]
    get_active_session_id: Callable[[Any], str | None]
    now_iso: Callable[[], str]
    default_session_title: str
    title_state_ready: str
    title_state_idle: str
    max_sessions: int


class ChatSessionApplicationService:
    """Owns project/session mutations and their persistence boundary."""

    def __init__(
        self,
        dependencies: ChatSessionApplicationDependencies,
    ) -> None:
        self._deps = dependencies

    def archive_session(
        self,
        state: Any,
        session_id: str,
    ) -> dict[str, Any] | None:
        session, store = self._deps.find_session(state, session_id)
        if session is None:
            return None

        changed = False
        if not bool(session.get("is_archived", False)):
            session["is_archived"] = True
            changed = True

        if store.get("active_session_id") == session["id"]:
            store["active_session_id"] = None
            state.active_chat_session_id = None
            self._deps.touch_chat(state)
            changed = True

        if not changed:
            return self._deps.serialize_session_detail(
                session,
                store,
                state,
            )

        session["updated_at"] = self._deps.now_iso()
        self._deps.touch_sessions(state)
        self._deps.persist_store(state, session_ids={str(session["id"])})
        return self._deps.serialize_session_detail(session, store, state)

    def create_project(
        self,
        state: Any,
        *,
        name: str,
        root_path: str | None = None,
        python_interpreter_path: str | None = None,
        aiida_profile: str | None = None,
        activate: bool = True,
    ) -> dict[str, Any]:
        cleaned_name = self._deps.trim_text(name or "", limit=80)
        if not cleaned_name:
            raise ValueError("Project name is required")

        store = self._deps.get_store(state)
        project_id = uuid4().hex
        normalized_root_path = self._deps.validate_project_root(
            root_path,
            project_id=project_id,
        )
        if any(
            str(project.get("root_path") or "") == normalized_root_path
            for project in store.get("projects", [])
        ):
            raise ValueError("A project with the same disk path already exists")

        now = self._deps.now_iso()
        project = {
            "id": project_id,
            "name": cleaned_name,
            "root_path": normalized_root_path,
            "python_interpreter_path": str(python_interpreter_path or "").strip() or None,
            "aiida_profile": str(aiida_profile or "").strip() or None,
            "created_at": now,
            "updated_at": now,
        }
        store["projects"].append(project)
        self._deps.ensure_project_workspace(project)
        if activate:
            store["active_project_id"] = project_id
            state.active_chat_project_id = project_id
        self._deps.touch_sessions(state)
        self._deps.persist_store(state, session_ids=set())
        return self._deps.serialize_project(project, store)

    def update_project(
        self,
        state: Any,
        project_id: str,
        *,
        python_interpreter_path: str | None = None,
        aiida_profile: str | None = None,
        group_uuid: str | None = None,
        group_label: str | None = None,
    ) -> dict[str, Any]:
        store = self._deps.get_store(state)
        project = next((p for p in store.get("projects", []) if p["id"] == project_id), None)
        if not project:
            raise ValueError("Project not found")

        if python_interpreter_path is not None:
            project["python_interpreter_path"] = python_interpreter_path.strip() or None
        if aiida_profile is not None:
            project["aiida_profile"] = aiida_profile.strip() or None
        if group_uuid is not None:
            project["group_uuid"] = group_uuid.strip() or None
        if group_label is not None:
            project["group_label"] = group_label.strip() or None

        project["updated_at"] = self._deps.now_iso()
        self._deps.touch_sessions(state)
        self._deps.persist_store(state, session_ids=set())
        return self._deps.serialize_project(project, store)

    def create_session(
        self,
        state: Any,
        *,
        title: str | None = None,
        snapshot: dict[str, Any] | None = None,
        activate: bool = True,
        archive_session_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        store = self._deps.get_store(state)
        if isinstance(archive_session_id, str) and archive_session_id.strip():
            self.archive_session(state, archive_session_id.strip())
            store = self._deps.get_store(state)

        now = self._deps.now_iso()
        cleaned_title = self._deps.sanitize_title(title or "")[:80].strip()
        resolved_project_id = self._deps.resolve_project_id(
            store,
            requested_project_id=project_id,
        )
        session_id = uuid4().hex
        session_title = cleaned_title or self._deps.default_session_title
        session = {
            "id": session_id,
            "project_id": resolved_project_id,
            "title": session_title,
            "session_slug": self._deps.resolve_session_slug(
                store,
                resolved_project_id,
                self._deps.slugify_session_name(
                    session_title,
                    fallback="new-conversation",
                ),
                session_id=session_id,
            ),
            "auto_title": not bool(cleaned_title),
            "title_state": (
                self._deps.title_state_ready
                if cleaned_title
                else self._deps.title_state_idle
            ),
            "title_first_intent": None,
            "title_last_generated_turn": 0,
            "title_generation_count": 0,
            "title_last_context_key": None,
            "is_archived": False,
            "created_at": now,
            "updated_at": now,
            "tags": [],
            "workspace_path": None,
            "snapshot": self._deps.normalize_snapshot(snapshot),
            "messages": [],
        }
        store["sessions"].append(session)
        store["sessions"] = store["sessions"][-self._deps.max_sessions :]
        self._deps.ensure_session_workspace(store, session)
        if activate:
            store["active_session_id"] = session["id"]
            store["active_project_id"] = resolved_project_id
            state.active_chat_session_id = session["id"]
            state.active_chat_project_id = resolved_project_id
            self._deps.touch_chat(state)
        self._deps.touch_sessions(state)
        self._deps.persist_store(state, session_ids={str(session["id"])})
        return self._deps.serialize_session_detail(session, store, state)

    def activate_session(
        self,
        state: Any,
        session_id: str,
    ) -> dict[str, Any] | None:
        session, store = self._deps.find_session(state, session_id)
        if session is None:
            return None
        session_changed = False
        selection_changed = False
        if bool(session.get("is_archived", False)):
            session["is_archived"] = False
            session_changed = True
        if store.get("active_session_id") != session["id"]:
            store["active_session_id"] = session["id"]
            store["active_project_id"] = str(
                session.get("project_id")
                or store.get("active_project_id")
                or ""
            )
            state.active_chat_session_id = session["id"]
            state.active_chat_project_id = store["active_project_id"]
            self._deps.touch_chat(state)
            selection_changed = True
        if session_changed or selection_changed:
            self._deps.touch_sessions(state)
            self._deps.persist_store(
                state,
                session_ids={str(session["id"])} if session_changed else set(),
            )
        return self._deps.serialize_session_detail(session, store, state)

    def update_session(
        self,
        state: Any,
        session_id: str,
        *,
        title: str | object = SESSION_FIELD_UNSET,
        tags: list[str] | object = SESSION_FIELD_UNSET,
        snapshot: dict[str, Any] | object = SESSION_FIELD_UNSET,
    ) -> dict[str, Any] | None:
        session, store = self._deps.find_session(state, session_id)
        if session is None:
            return None

        changed = False
        if title is not SESSION_FIELD_UNSET:
            old_slug = self._deps.get_session_slug(session)
            cleaned_title = self._deps.sanitize_title(title or "")[:80].strip()
            resolved_title = (
                cleaned_title or self._deps.default_session_title
            )
            session["title"] = resolved_title
            session["session_slug"] = self._deps.desired_session_slug(
                store,
                session,
                resolved_title,
            )
            session["auto_title"] = not bool(cleaned_title)
            session["title_state"] = (
                self._deps.title_state_ready
                if cleaned_title
                else self._deps.title_state_idle
            )
            if not cleaned_title:
                session["title_generation_count"] = 0
                session["title_last_generated_turn"] = 0
                session["title_last_context_key"] = None
            self._deps.ensure_session_workspace(store, session)
            self._deps.rename_session_group(
                state,
                store,
                session,
                old_slug,
            )
            changed = True
        if tags is not SESSION_FIELD_UNSET:
            session["tags"] = self._deps.normalize_tags(tags)
            changed = True
        if snapshot is not SESSION_FIELD_UNSET:
            session["snapshot"] = self._deps.normalize_snapshot(snapshot)
            changed = True

        if not changed:
            return self._deps.serialize_session_detail(
                session,
                store,
                state,
            )

        session["updated_at"] = self._deps.now_iso()
        self._deps.touch_sessions(state)
        if self._deps.get_active_session_id(state) == session["id"]:
            self._deps.touch_chat(state)
        self._deps.persist_store(state, session_ids={str(session["id"])})
        return self._deps.serialize_session_detail(session, store, state)

    def delete_items(
        self,
        state: Any,
        *,
        project_ids: list[str] | None = None,
        session_ids: list[str] | None = None,
    ) -> dict[str, list[str]]:
        normalized_project_ids = set(
            self._deps.normalize_identifier_list(project_ids)
        )
        normalized_session_ids = set(
            self._deps.normalize_identifier_list(session_ids)
        )
        if not normalized_project_ids and not normalized_session_ids:
            return {"deleted_project_ids": [], "deleted_session_ids": []}

        store = self._deps.get_store(state)
        existing_projects = {
            str(project.get("id") or "").strip(): project
            for project in store.get("projects", [])
            if isinstance(project, dict)
            and str(project.get("id") or "").strip()
        }
        existing_sessions = {
            str(session.get("id") or "").strip(): session
            for session in store.get("sessions", [])
            if isinstance(session, dict)
            and str(session.get("id") or "").strip()
        }

        matched_project_ids = normalized_project_ids.intersection(
            existing_projects
        )
        matched_session_ids = normalized_session_ids.intersection(
            existing_sessions
        )
        matched_session_ids.update(
            str(session.get("id") or "").strip()
            for session in existing_sessions.values()
            if str(session.get("project_id") or "").strip()
            in matched_project_ids
        )

        if not matched_project_ids and not matched_session_ids:
            return {"deleted_project_ids": [], "deleted_session_ids": []}

        for project_id in matched_project_ids:
            project = existing_projects.get(project_id)
            if isinstance(project, dict):
                self._deps.cleanup_project_workspace(project)

        store["sessions"] = [
            session
            for session in store.get("sessions", [])
            if isinstance(session, dict)
            and str(session.get("id") or "").strip()
            not in matched_session_ids
        ]
        store["projects"] = [
            project
            for project in store.get("projects", [])
            if isinstance(project, dict)
            and str(project.get("id") or "").strip()
            not in matched_project_ids
        ]

        deleted_project_ids = sorted(matched_project_ids)
        deleted_session_ids = sorted(matched_session_ids)
        self._deps.reconcile_active_targets(state, store)
        self._deps.touch_sessions(state)
        self._deps.touch_chat(state)
        self._deps.persist_store(state, session_ids=set())
        return {
            "deleted_project_ids": deleted_project_ids,
            "deleted_session_ids": deleted_session_ids,
        }


__all__ = [
    "ChatSessionApplicationDependencies",
    "ChatSessionApplicationService",
    "SESSION_FIELD_UNSET",
]
