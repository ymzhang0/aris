"""Tests for the canonical AiiDA worker status endpoint."""

import asyncio

from src.aris_apps.aiida.client import AiiDAWorkerClient


def test_get_status_refresh_not_blocked_by_other_bridge_calls() -> None:
    service = AiiDAWorkerClient(bridge_url="http://127.0.0.1:8001")
    calls = {"status": 0}

    async def fake_fetch_json(
        path: str,
        *,
        timeout_seconds: float | None = None,
    ) -> object:
        _ = timeout_seconds
        if path == "/resources":
            return {
                "computers": [{"label": "localhost"}],
                "codes": [{"label": "pw"}],
            }
        if path == "/status":
            calls["status"] += 1
            return {
                "status": "online",
                "profile": "default",
                "daemon_status": True,
                "counts": {"computers": 1, "codes": 1, "workchains": 1},
                "plugins": ["quantumespresso.pw.relax"],
            }
        raise AssertionError(f"Unexpected path: {path}")

    service._fetch_json = fake_fetch_json  # type: ignore[method-assign]

    _ = asyncio.run(service.get_resources())
    snapshot = asyncio.run(service.get_status(force_refresh=False))

    assert calls["status"] == 1
    assert snapshot.status == "online"
    assert snapshot.plugins == ["quantumespresso.pw.relax"]


def test_missing_canonical_status_marks_bridge_offline() -> None:
    service = AiiDAWorkerClient(bridge_url="http://127.0.0.1:8001")
    calls: list[str] = []

    async def fake_fetch_json(path: str, **_: object) -> object:
        calls.append(path)
        raise RuntimeError("worker offline")

    service._fetch_json = fake_fetch_json  # type: ignore[method-assign]

    snapshot = asyncio.run(service.get_status(force_refresh=True))

    assert calls == ["/status"]
    assert snapshot.status == "offline"


def test_explicit_offline_status_is_cached_as_authoritative() -> None:
    service = AiiDAWorkerClient(
        bridge_url="http://127.0.0.1:8001",
        cache_ttl_seconds=60.0,
    )

    async def fake_fetch_json(path: str, **_: object) -> object:
        assert path == "/status"
        return {"status": "offline", "mode": "core-injected-executor"}

    service._fetch_json = fake_fetch_json  # type: ignore[method-assign]

    first = asyncio.run(service.get_status(force_refresh=True))
    second = asyncio.run(service.get_status(force_refresh=False))

    assert first.status == "offline"
    assert second.status == "offline"
    assert service._snapshot.checked_at > 0  # noqa: SLF001
