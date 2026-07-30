from __future__ import annotations

import base64

import pytest

from src.aris_apps.aiida.client import (
    AiiDAWorkerClient,
    BridgeAPIError,
    _map_request_to_rpc,
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
    assert aiida_worker_client.bridge_url == "stdio://managed-aiida-worker"


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


@pytest.mark.parametrize(
    ("method", "path", "expected_method", "expected_params"),
    [
        ("GET", "/management/statistics", "system.statistics", {}),
        ("GET", "/management/database/summary", "system.database_summary", {}),
        ("GET", "/management/groups/Si%20batch", "group.inspect", {"group_name": "Si batch"}),
        ("POST", "/management/groups/4/nodes", "group.add_nodes", {"pk": 4}),
        ("GET", "/management/nodes/12", "node.summary", {"pk": 12}),
        ("GET", "/data/repository/7/files/out.txt", "data.repository_file", {"pk": 7, "filename": "out.txt"}),
        ("POST", "/execute/eos-fit", "registry.execute", {"script_name": "eos-fit"}),
    ],
)
def test_url_facade_maps_to_explicit_rpc_capabilities(
    method: str,
    path: str,
    expected_method: str,
    expected_params: dict[str, object],
) -> None:
    mapped = _map_request_to_rpc(method, path)
    assert mapped is not None
    assert mapped[0] == expected_method
    assert mapped[1] == expected_params


@pytest.mark.anyio
async def test_request_json_uses_only_managed_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _ManagedWorker({"items": []})
    monkeypatch.setattr("src.aris_apps.aiida.client.get_worker_process_manager", lambda: worker)
    client = AiiDAWorkerClient(bridge_url="stdio://managed-aiida-worker")

    result = await client.request_json(
        "GET",
        "/management/recent-nodes",
        params={"limit": 8},
        context=build_worker_context(
            session_id="session-1",
            project_id="project-1",
            workspace_path="/tmp/project",
            python_path="/tmp/project/.venv/bin/python",
        ),
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
    client = AiiDAWorkerClient(bridge_url="stdio://managed-aiida-worker")

    with pytest.raises(BridgeAPIError) as error:
        await client.request_json("GET", "/management/nodes/99")

    assert error.value.status_code == 404
    assert error.value.payload["kind"] == "not_found"


@pytest.mark.anyio
async def test_multipart_import_is_encoded_inside_json_rpc(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = _ManagedWorker({"status": "success", "pk": 3})
    monkeypatch.setattr("src.aris_apps.aiida.client.get_worker_process_manager", lambda: worker)
    client = AiiDAWorkerClient(bridge_url="stdio://managed-aiida-worker")

    result = await client.request_multipart(
        "POST",
        "/data/import/structure",
        files={"file": ("si.xyz", b"2\nSi\nSi 0 0 0\nSi 1 1 1\n", "chemical/x-xyz")},
        data={"source_type": "file", "label": "Si"},
    )

    assert result["pk"] == 3
    method, params, _ = worker.calls[0]
    assert method == "data.import"
    assert params["filename"] == "si.xyz"
    assert base64.b64decode(str(params["content_base64"])).startswith(b"2\nSi")


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
    client = AiiDAWorkerClient(bridge_url="stdio://managed-aiida-worker")

    snapshot = await client.get_status(force_refresh=True)

    assert snapshot.status == "online"
    assert snapshot.mode == "managed-subprocess"
    assert snapshot.profile == "dev"
    assert snapshot.resources.codes == 2
    assert worker.calls[0][0] == "runtime.status"
