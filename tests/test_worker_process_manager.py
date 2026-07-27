from __future__ import annotations

import asyncio
import json
import sys

from src.aris_core.runtime import WorkerProcessError, WorkerProcessManager


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
