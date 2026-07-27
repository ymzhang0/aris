"""Read-side application service for chat projects and sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

GetStore = Callable[[Any], dict[str, Any]]
FindSession = Callable[
    [Any, str | None],
    tuple[dict[str, Any] | None, dict[str, Any]],
]
SerializeProject = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
SerializeSession = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
SerializeSessionDetail = Callable[
    [dict[str, Any], dict[str, Any], Any | None],
    dict[str, Any],
]
SerializeSnapshot = Callable[[dict[str, Any] | None], dict[str, Any]]
SerializeHistory = Callable[[Any], list[dict[str, Any]]]


@dataclass(frozen=True)
class ChatSessionQueryDependencies:
    """Persistence and presentation operations needed by session queries."""

    get_store: GetStore
    find_session: FindSession
    serialize_project: SerializeProject
    serialize_session: SerializeSession
    serialize_session_detail: SerializeSessionDetail
    serialize_snapshot: SerializeSnapshot
    serialize_history: SerializeHistory


class ChatSessionQueryService:
    """Provides the read-side project/session application API."""

    def __init__(self, dependencies: ChatSessionQueryDependencies) -> None:
        self._deps = dependencies

    def list_projects(self, state: Any) -> list[dict[str, Any]]:
        store = self._deps.get_store(state)
        projects = sorted(
            store["projects"],
            key=lambda project: self._deps.serialize_project(
                project,
                store,
            )["updated_at"],
            reverse=True,
        )
        return [
            self._deps.serialize_project(project, store)
            for project in projects
        ]

    def list_sessions(self, state: Any) -> list[dict[str, Any]]:
        store = self._deps.get_store(state)
        sessions = sorted(
            store["sessions"],
            key=lambda session: str(
                session.get("updated_at") or session.get("created_at") or ""
            ),
            reverse=True,
        )
        return [
            self._deps.serialize_session(session, store)
            for session in sessions
        ]

    def get_active_project_id(self, state: Any) -> str | None:
        store = self._deps.get_store(state)
        active_project_id = store.get("active_project_id")
        if isinstance(active_project_id, str) and active_project_id:
            return active_project_id
        return None

    def get_active_session_id(self, state: Any) -> str | None:
        store = self._deps.get_store(state)
        active_session_id = store.get("active_session_id")
        if isinstance(active_session_id, str) and active_session_id:
            return active_session_id
        return None

    def get_session_detail(
        self,
        state: Any,
        session_id: str,
    ) -> dict[str, Any] | None:
        session, store = self._deps.find_session(state, session_id)
        if session is None:
            return None
        return self._deps.serialize_session_detail(session, store, state)

    def get_snapshot(self, state: Any) -> dict[str, Any]:
        session, _store = self._deps.find_session(state, None)
        return {
            "version": int(getattr(state, "chat_version", 0)),
            "session_id": (
                session["id"] if isinstance(session, dict) else None
            ),
            "messages": self._deps.serialize_history(
                session.get("messages", [])
                if isinstance(session, dict)
                else []
            ),
            "snapshot": self._deps.serialize_snapshot(session),
        }

    def get_history(
        self,
        state: Any,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        session, store = self._deps.find_session(state, session_id)
        if session is None:
            state.active_chat_session_id = store.get("active_session_id")
            if not hasattr(state, "chat_version"):
                state.chat_version = 0
            return []
        if not hasattr(state, "chat_version"):
            state.chat_version = 0
        return session["messages"]


__all__ = [
    "ChatSessionQueryDependencies",
    "ChatSessionQueryService",
]
