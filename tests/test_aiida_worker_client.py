from __future__ import annotations

import base64

import pytest

from src.aris_apps.aiida.client import (
    AiiDAWorkerClient,
    WorkerRPCError,
    aiida_worker_client,
    build_worker_context,
    get_aiida_worker_client,
)
from src.aris_core.runtime import WorkerProcessError


class _ManagedWorker:
    def __init__(self, result: dict[str, object] | None = None) -> None:
        self.result = result or {"status": "ok"}
        self.calls: list[tuple[str, dict[str, object], float | None]] = []

    async def request(self, method: str, params=None, *, timeout=None):
        self.calls.append((method, dict(params or {}), timeout))
        return dict(self.result)


def test_worker_client_singleton_is_stable() -> None:
    assert get_aiida_worker_client() is aiida_worker_client


def test_build_worker_context_emits_protocol_fields() -> None:
    assert build_worker_context(
        session_id="chat-0308",
        project_id="proj-0308",
        workspace_path="/tmp/aris-session",
        python_path="/tmp/aris-session/.venv/bin/python",
    ) == {
        "session_id": "chat-0308",
        "project_id": "proj-0308",
        "workspace_path": "/tmp/aris-session",
        "python_interpreter_path": "/tmp/aris-session/.venv/bin/python",
    }


@pytest.mark.anyio
async def test_worker_call_uses_only_managed_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _ManagedWorker({"items": []})
    monkeypatch.setattr("src.aris_apps.aiida.client.get_worker_process_manager", lambda: worker)
    client = AiiDAWorkerClient()

    result = await client.call(
        "node.recent",
        params={"limit": 8},
        context=build_worker_context(
            session_id="session-1",
            project_id="project-1",
            workspace_path="/tmp/project",
            python_path="/tmp/project/.venv/bin/python",
        ),
        timeout=10.0,
    )

    assert result == {"items": []}
    assert worker.calls == [
        (
            "node.recent",
            {
                "limit": 8,
                "session_id": "session-1",
                "project_id": "project-1",
                "workspace_path": "/tmp/project",
                "python_interpreter_path": "/tmp/project/.venv/bin/python",
            },
            10.0,
        )
    ]


@pytest.mark.anyio
async def test_worker_domain_error_preserves_status_and_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingWorker:
        async def request(self, *_args, **_kwargs):
            raise WorkerProcessError(
                "Node not found",
                status_code=404,
                payload={"error": "Node not found", "kind": "not_found", "pk": 99},
            )

    monkeypatch.setattr("src.aris_apps.aiida.client.get_worker_process_manager", lambda: _FailingWorker())
    client = AiiDAWorkerClient()

    with pytest.raises(WorkerRPCError) as error:
        await client.call("node.summary", {"pk": 99})

    assert error.value.status_code == 404
    assert error.value.payload["kind"] == "not_found"


@pytest.mark.anyio
async def test_status_refresh_uses_managed_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _ManagedWorker(
        {
            "status": "online",
            "transport": "stdio-jsonrpc",
            "mode": "managed-subprocess",
            "profile": "dev",
            "resources": {"computers": 1, "codes": 2, "workchains": 3},
            "plugins": ["quantumespresso.pw.base"],
        }
    )
    monkeypatch.setattr("src.aris_apps.aiida.client.get_worker_process_manager", lambda: worker)
    client = AiiDAWorkerClient()

    snapshot = await client.get_status(force_refresh=True)

    assert snapshot.status == "online"
    assert snapshot.mode == "managed-subprocess"
    assert snapshot.profile == "dev"
    assert snapshot.resources.codes == 2
    assert worker.calls[0][0] == "runtime.status"

