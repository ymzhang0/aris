"""Tests for managed AiiDA worker status caching."""

import asyncio

from src.aris_apps.aiida.client import AiiDAWorkerClient


class _Worker:
    def __init__(self, payload=None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls = 0

    async def request(self, method, params=None, *, timeout=None):
        del params, timeout
        assert method == "runtime.status"
        self.calls += 1
        if self.error:
            raise self.error
        return dict(self.payload or {})


def test_get_status_uses_one_managed_worker_probe(monkeypatch) -> None:
    worker = _Worker(
        {
            "status": "online",
            "profile": "default",
            "daemon_status": True,
            "resources": {"computers": 1, "codes": 1, "workchains": 1},
            "plugins": ["quantumespresso.pw.relax"],
        }
    )
    monkeypatch.setattr("src.aris_apps.aiida.client.get_worker_process_manager", lambda: worker)
    service = AiiDAWorkerClient(bridge_url="stdio://managed-aiida-worker")

    snapshot = asyncio.run(service.get_status(force_refresh=True))

    assert worker.calls == 1
    assert snapshot.status == "online"
    assert snapshot.plugins == ["quantumespresso.pw.relax"]


def test_managed_worker_failure_marks_runtime_offline(monkeypatch) -> None:
    worker = _Worker(error=RuntimeError("worker offline"))
    monkeypatch.setattr("src.aris_apps.aiida.client.get_worker_process_manager", lambda: worker)
    service = AiiDAWorkerClient(bridge_url="stdio://managed-aiida-worker")

    snapshot = asyncio.run(service.get_status(force_refresh=True))

    assert worker.calls == 1
    assert snapshot.status == "offline"


def test_status_snapshot_is_cached(monkeypatch) -> None:
    worker = _Worker({"status": "online", "mode": "managed-subprocess"})
    monkeypatch.setattr("src.aris_apps.aiida.client.get_worker_process_manager", lambda: worker)
    service = AiiDAWorkerClient(
        bridge_url="stdio://managed-aiida-worker",
        cache_ttl_seconds=60.0,
    )

    first = asyncio.run(service.get_status(force_refresh=True))
    second = asyncio.run(service.get_status(force_refresh=False))

    assert first.status == second.status == "online"
    assert worker.calls == 1
