from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from src.aris_core import runtime as runtime_package
from src.aris_core.runtime import (
    ProjectWorkerProcessManager,
    WorkerProcessError,
    WorkerProcessManager,
    WorkerRuntimeKey,
)


FAKE_WORKER = """
import json
import os
import sys

for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    if method == "runtime.shutdown":
        result = {"status": "shutting_down"}
    elif method == "runtime.status":
        result = {"status": "online", "pid": os.getpid(), "transport": "stdio-jsonrpc"}
    elif method == "echo":
        result = request.get("params", {})
    elif method == "invalid":
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {"code": -32602, "message": "Invalid params", "data": {"reason": "bad input"}},
        }
        print(json.dumps(response), flush=True)
        continue
    elif method == "exit":
        raise SystemExit(7)
    else:
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {"code": -32601, "message": "Method not found", "data": {"method": method}},
        }
        print(json.dumps(response), flush=True)
        continue

    response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
    print(json.dumps(response), flush=True)
    if method == "runtime.shutdown":
        break
"""


def test_worker_process_manager_owns_one_reusable_process() -> None:
    async def run() -> None:
        manager = WorkerProcessManager([sys.executable, "-u", "-c", FAKE_WORKER])

        started = await manager.start()
        echoed = await manager.request("echo", {"value": 42})
        second_status = await manager.request("runtime.status")

        assert started["status"] == "online"
        assert echoed == {"value": 42}
        assert second_status["pid"] == started["pid"]
        assert manager.snapshot().status == "online"
        assert manager.snapshot().pid == started["pid"]

        await manager.stop()
        assert manager.snapshot().status == "offline"
        assert manager.snapshot().pid is None

    asyncio.run(run())


def test_worker_process_manager_can_start_again_after_clean_shutdown() -> None:
    async def run() -> None:
        manager = WorkerProcessManager([sys.executable, "-u", "-c", FAKE_WORKER])

        first = await manager.start()
        await manager.stop()
        second = await manager.start()

        assert first["pid"] != second["pid"]
        assert manager.snapshot().restart_count == 0
        await manager.stop()

    asyncio.run(run())


def test_worker_process_manager_restarts_after_worker_crash() -> None:
    async def run() -> None:
        manager = WorkerProcessManager([sys.executable, "-u", "-c", FAKE_WORKER])
        first = await manager.start()

        try:
            await manager.request("exit")
        except WorkerProcessError:
            pass
        else:
            raise AssertionError("Expected the crashed worker request to fail")

        second = await manager.start()

        assert first["pid"] != second["pid"]
        assert manager.snapshot().restart_count == 1
        await manager.stop()

    asyncio.run(run())


def test_worker_process_manager_maps_json_rpc_invalid_params_to_422() -> None:
    async def run() -> None:
        manager = WorkerProcessManager([sys.executable, "-u", "-c", FAKE_WORKER])

        try:
            await manager.request("invalid")
        except WorkerProcessError as exc:
            assert exc.status_code == 422
            assert exc.payload["reason"] == "bad input"
        else:
            raise AssertionError("Expected invalid params to fail")
        finally:
            await manager.stop()

    asyncio.run(run())


def test_worker_runtime_key_includes_project_interpreter_and_profile() -> None:
    base = {
        "project_id": "project-a",
        "python_interpreter_path": sys.executable,
    }

    dev = WorkerRuntimeKey.from_context({**base, "profile_name": "dev"})
    test = WorkerRuntimeKey.from_context({**base, "profile_name": "test"})

    assert dev != test
    assert dev.project_id == "project-a"
    assert dev.python_interpreter_path == sys.executable


def test_project_worker_manager_routes_each_runtime_to_one_verified_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[object] = []

    class FakeWorkerProcessManager:
        def __init__(self, command, *, cwd=None, env=None, request_timeout=10.0) -> None:
            self.command = tuple(command)
            self.cwd = cwd
            self.env = dict(env or {})
            self.stopped = False
            created.append(self)

        async def start(self):
            return {
                "status": "online",
                "transport": "stdio-jsonrpc",
                "python_interpreter_path": self.command[0],
                "profile": self.env.get("AIIDA_PROFILE"),
            }

        async def request(self, method, params=None, *, context=None, timeout=None):
            return {
                "method": method,
                "params": dict(params or {}),
                "context": dict(context or {}),
                "profile": self.env.get("AIIDA_PROFILE"),
            }

        def snapshot(self):
            return runtime_package.WorkerProcessSnapshot(
                status="online",
                pid=123,
                command=self.command,
                cwd=self.cwd,
                restart_count=0,
                last_error=None,
            )

        async def stop(self):
            self.stopped = True

    monkeypatch.setattr(
        "src.aris_core.runtime.worker_process.WorkerProcessManager",
        FakeWorkerProcessManager,
    )

    async def run() -> None:
        manager = ProjectWorkerProcessManager(
            runtime_context_provider=lambda: {
                "project_id": "project-a",
                "python_interpreter_path": sys.executable,
                "profile_name": "dev",
            },
            worker_package_source="../aiida-worker",
        )
        first = await manager.request("echo", {"value": 1})
        second = await manager.request("echo", {"value": 2})
        other = await manager.request(
            "echo",
            {"value": 3},
            context={
                "project_id": "project-a",
                "python_interpreter_path": sys.executable,
                "profile_name": "test",
            },
        )

        assert len(created) == 2
        assert created[0].command[2].endswith("worker_bootstrap.py")
        assert created[0].command[3].endswith("aiida-worker")
        assert first["profile"] == "dev"
        assert second["profile"] == "dev"
        assert other["profile"] == "test"
        await manager.stop()
        assert all(item.stopped for item in created)

    asyncio.run(run())


def test_central_worker_source_runs_with_project_python() -> None:
    worker_root = Path(__file__).resolve().parents[2] / "aiida-worker"
    project_python = worker_root / ".venv" / "bin" / "python"
    if not project_python.is_file():
        pytest.skip("aiida-worker development environment is unavailable")

    async def run() -> None:
        manager = ProjectWorkerProcessManager(
            runtime_context_provider=lambda: None,
            worker_package_source=worker_root,
        )
        status = await manager.start(
            context={
                "project_id": "integration-project",
                "python_interpreter_path": str(project_python),
                "workspace_path": str(worker_root),
            }
        )
        snapshot = manager.snapshot()

        assert status["status"] == "online"
        assert Path(status["python_interpreter_path"]).samefile(project_python)
        assert snapshot.command[0] == str(project_python)
        assert snapshot.command[2].endswith("worker_bootstrap.py")
        assert snapshot.command[3] == str(worker_root)
        assert "-m" not in snapshot.command
        await manager.stop()

    asyncio.run(run())
