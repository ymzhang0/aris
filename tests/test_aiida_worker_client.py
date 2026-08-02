from __future__ import annotations

import base64

import pytest

from src.aris_apps.aiida.client import (
    AiiDAWorkerClient,
    WorkerRPCError,
    aiida_worker_client,
    build_worker_context,
    get_aiida_worker_client,
    import_worker_data,
    optional_worker_call,
)
from src.aris_core.runtime import WorkerProcessError


class _ManagedWorker:
    def __init__(self, result: dict[str, object] | None = None) -> None:
        self.result = result or {"status": "ok"}
        self.calls: list[tuple[str, dict[str, object], dict[str, object], float | None]] = []

    async def request(self, method: str, params=None, *, context=None, timeout=None):
        self.calls.append((method, dict(params or {}), dict(context or {}), timeout))
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
            },
            {
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


def test_worker_rpc_error_surfaces_invalid_parameter_reason() -> None:
    error = WorkerRPCError(
        422,
        "Invalid params",
        {"reason": "session_id: extra inputs are not permitted"},
    )

    assert str(error) == (
        "RPC Error 422: Invalid params "
        "(session_id: extra inputs are not permitted)"
    )


@pytest.mark.anyio
async def test_optional_worker_call_only_suppresses_optional_rpc_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def missing(*_args, **_kwargs):
        raise WorkerRPCError(404, "Node not found", {"pk": 99})

    monkeypatch.setattr("src.aris_apps.aiida.client.worker_call", missing)

    assert await optional_worker_call("node.summary", {"pk": 99}) is None


@pytest.mark.anyio
async def test_import_worker_data_encodes_file_for_json_rpc(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def capture(method, params=None, **kwargs):
        captured.update({"method": method, "params": params, **kwargs})
        return {"pk": 42}

    monkeypatch.setattr("src.aris_apps.aiida.client.worker_call", capture)

    result = await import_worker_data(
        data_type="structure",
        source_type="file",
        label="Silicon",
        filename="si.cif",
        file_content=b"data_Si",
    )

    assert result == {"pk": 42}
    assert captured == {
        "method": "data.import",
        "params": {
            "data_type": "structure",
            "source_type": "file",
            "label": "Silicon",
            "filename": "si.cif",
            "content_base64": base64.b64encode(b"data_Si").decode("ascii"),
        },
        "timeout": 30.0,
    }


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
