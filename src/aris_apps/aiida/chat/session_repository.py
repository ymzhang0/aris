"""Persistence boundary for ARIS chat session indexes and message files."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from loguru import logger

from src.aris_core.logging import log_event

CHAT_SESSIONS_KV_KEY = "frontend_chat_sessions_v2"
LEGACY_CHAT_SESSIONS_KV_KEY = "frontend_chat_sessions_v1"
SESSIONS_DIRNAME = "sessions"


class ChatSessionRepository(Protocol):
    def load_index(self, memory: Any) -> Any: ...

    def load_session(self, session_id: str) -> dict[str, Any] | None: ...

    def save(
        self,
        memory: Any,
        *,
        index_payload: dict[str, Any],
        session_payloads: Mapping[str, dict[str, Any]],
    ) -> None: ...


class JsonChatSessionRepository:
    """JSON implementation preserving the current on-disk storage contract."""

    def __init__(self, memory_root_provider: Callable[[], str | Path]) -> None:
        self._memory_root_provider = memory_root_provider

    def _storage_root(self) -> Path:
        raw_root = str(self._memory_root_provider() or "").strip()
        root = Path(raw_root).expanduser().resolve() if raw_root else Path.home() / ".aris" / "memories"
        sessions_root = root / SESSIONS_DIRNAME
        sessions_root.mkdir(parents=True, exist_ok=True)
        return sessions_root

    @staticmethod
    def _safe_storage_name(session_id: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(session_id or "").strip()).strip(".-")
        return cleaned or uuid4().hex

    def _session_file_path(self, session_id: str) -> Path:
        return self._storage_root() / f"{self._safe_storage_name(session_id)}.json"

    def load_index(self, memory: Any) -> Any:
        getter = getattr(memory, "get_kv", None)
        if not callable(getter):
            return None
        raw_store = getter(CHAT_SESSIONS_KV_KEY)
        if raw_store is None:
            raw_store = getter(LEGACY_CHAT_SESSIONS_KV_KEY)
        return raw_store

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        target = self._session_file_path(session_id)
        if not target.exists() or not target.is_file():
            return None
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.warning(
                log_event(
                    "aiida.chat_session.file_load_failed",
                    session_id=session_id,
                    path=str(target),
                )
            )
            return None
        return payload if isinstance(payload, dict) else None

    def _write_session(self, session_id: str, payload: dict[str, Any]) -> str:
        storage_name = self._safe_storage_name(session_id)
        target = self._storage_root() / f"{storage_name}.json"
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        if target.exists():
            with suppress(OSError):
                if target.read_text(encoding="utf-8") == serialized:
                    return storage_name
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(target)
        return storage_name

    def save(
        self,
        memory: Any,
        *,
        index_payload: dict[str, Any],
        session_payloads: Mapping[str, dict[str, Any]],
    ) -> None:
        active_names = {
            self._write_session(session_id, payload)
            for session_id, payload in session_payloads.items()
            if str(session_id).strip()
        }
        for child in self._storage_root().glob("*.json"):
            if child.stem.strip() in active_names:
                continue
            with suppress(OSError):
                child.unlink()

        setter = getattr(memory, "set_kv", None)
        if callable(setter):
            setter(CHAT_SESSIONS_KV_KEY, index_payload)


__all__ = [
    "CHAT_SESSIONS_KV_KEY",
    "ChatSessionRepository",
    "JsonChatSessionRepository",
    "LEGACY_CHAT_SESSIONS_KV_KEY",
    "SESSIONS_DIRNAME",
]

