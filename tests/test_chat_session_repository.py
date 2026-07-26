from __future__ import annotations

import json
from pathlib import Path

from src.aris_apps.aiida.chat.session_repository import (
    CHAT_SESSIONS_KV_KEY,
    LEGACY_CHAT_SESSIONS_KV_KEY,
    JsonChatSessionRepository,
)
from src.aris_apps.aiida.chat import service as chat_service


class MemoryStub:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get_kv(self, key: str):
        return self.values.get(key)

    def set_kv(self, key: str, value: object) -> None:
        self.values[key] = value


def test_repository_loads_legacy_index_when_current_key_is_missing(tmp_path: Path) -> None:
    memory = MemoryStub()
    memory.values[LEGACY_CHAT_SESSIONS_KV_KEY] = {"version": 3}
    repository = JsonChatSessionRepository(lambda: tmp_path)

    assert repository.load_index(memory) == {"version": 3}


def test_repository_prefers_current_index_over_legacy(tmp_path: Path) -> None:
    memory = MemoryStub()
    memory.values[CHAT_SESSIONS_KV_KEY] = {"version": 4}
    memory.values[LEGACY_CHAT_SESSIONS_KV_KEY] = {"version": 3}
    repository = JsonChatSessionRepository(lambda: tmp_path)

    assert repository.load_index(memory) == {"version": 4}


def test_repository_saves_index_and_atomic_session_payload(tmp_path: Path) -> None:
    memory = MemoryStub()
    repository = JsonChatSessionRepository(lambda: tmp_path)
    session_payload = {
        "id": "session-1",
        "messages": [{"role": "user", "text": "hello"}],
    }

    repository.save(
        memory,
        index_payload={"version": 1, "sessions": [{"id": "session-1"}]},
        session_payloads={"session-1": session_payload},
    )

    session_file = tmp_path / "sessions" / "session-1.json"
    assert memory.values[CHAT_SESSIONS_KV_KEY] == {
        "version": 1,
        "sessions": [{"id": "session-1"}],
    }
    assert json.loads(session_file.read_text(encoding="utf-8")) == session_payload
    assert list((tmp_path / "sessions").glob("*.tmp")) == []


def test_repository_removes_orphaned_session_files(tmp_path: Path) -> None:
    memory = MemoryStub()
    repository = JsonChatSessionRepository(lambda: tmp_path)
    repository.save(
        memory,
        index_payload={"sessions": [{"id": "old-session"}]},
        session_payloads={"old-session": {"id": "old-session", "messages": []}},
    )

    repository.save(
        memory,
        index_payload={"sessions": [{"id": "new-session"}]},
        session_payloads={"new-session": {"id": "new-session", "messages": []}},
    )

    assert (tmp_path / "sessions" / "old-session.json").exists() is False
    assert (tmp_path / "sessions" / "new-session.json").is_file()


def test_repository_returns_none_for_corrupt_session_file(tmp_path: Path) -> None:
    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir(parents=True)
    (sessions_root / "broken.json").write_text("{", encoding="utf-8")
    repository = JsonChatSessionRepository(lambda: tmp_path)

    assert repository.load_session("broken") is None


def test_chat_service_accepts_an_injected_repository(tmp_path: Path) -> None:
    memory = MemoryStub()

    class RepositoryStub:
        def __init__(self) -> None:
            self.saved_indexes: list[dict[str, object]] = []

        def load_index(self, _memory):
            return {
                "version": 2,
                "turn_seq": 0,
                "active_project_id": None,
                "active_session_id": None,
                "projects": [],
                "sessions": [],
            }

        def load_session(self, _session_id: str):
            return None

        def save(self, _memory, *, index_payload, session_payloads):
            assert session_payloads == {}
            self.saved_indexes.append(index_payload)

    repository = RepositoryStub()
    state = type(
        "State",
        (),
        {
            "memory": memory,
            "chat_version": 0,
            "chat_session_repository": repository,
        },
    )()

    original_projects_root = chat_service.settings.ARIS_PROJECTS_ROOT
    chat_service.settings.ARIS_PROJECTS_ROOT = str(tmp_path / "projects")
    try:
        store = chat_service._get_chat_session_store(state)
    finally:
        chat_service.settings.ARIS_PROJECTS_ROOT = original_projects_root

    assert store["version"] == 2
    assert repository.saved_indexes
    assert memory.values == {}
