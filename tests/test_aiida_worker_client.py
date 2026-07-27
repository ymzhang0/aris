from __future__ import annotations

import time

import httpx
import pytest

from src.aris_apps.aiida.client import (
    AiiDAWorkerClient,
    BridgeAPIError,
    PROJECT_ID_HEADER,
    SESSION_ID_HEADER,
    WORKSPACE_PATH_HEADER,
    _merge_request_headers,
    aiida_worker_client,
    build_bridge_context_headers,
    get_aiida_worker_client,
)


def test_worker_client_singleton_is_stable() -> None:
    first = get_aiida_worker_client()
    second = get_aiida_worker_client()
    assert first is second
    assert aiida_worker_client is first


def test_build_bridge_context_headers_emits_canonical_headers() -> None:
    headers = build_bridge_context_headers(
        session_id="chat-0308",
        project_id="proj-0308",
        workspace_path="/tmp/aris-session",
    )

    assert headers == {
        SESSION_ID_HEADER: "chat-0308",
        PROJECT_ID_HEADER: "proj-0308",
        WORKSPACE_PATH_HEADER: "/tmp/aris-session",
    }


def test_merge_request_headers_keeps_canonical_bridge_headers() -> None:
    headers = _merge_request_headers(
        {
            SESSION_ID_HEADER: "chat-0308",
            PROJECT_ID_HEADER: "proj-0308",
            WORKSPACE_PATH_HEADER: "/tmp/aris-session",
        }
    )

    assert headers == {
        SESSION_ID_HEADER: "chat-0308",
        PROJECT_ID_HEADER: "proj-0308",
        WORKSPACE_PATH_HEADER: "/tmp/aris-session",
    }


def test_worker_client_is_connected_property_tracks_status() -> None:
    client = AiiDAWorkerClient(bridge_url="http://127.0.0.1:8001")
    assert client.is_connected is False
    client._mark_online()  # noqa: SLF001
    assert client.is_connected is True
    client._mark_offline()  # noqa: SLF001
    assert client.is_connected is False


def test_non_status_request_failure_does_not_poison_connection_state() -> None:
    client = AiiDAWorkerClient(bridge_url="http://127.0.0.1:8001")
    client._mark_online()  # noqa: SLF001

    client._record_status_failure("/resources")  # noqa: SLF001

    assert client.is_connected is True


def test_non_status_request_success_does_not_override_offline_probe() -> None:
    client = AiiDAWorkerClient(bridge_url="http://127.0.0.1:8001")
    client._mark_offline()  # noqa: SLF001

    client._record_status_success("/resources")  # noqa: SLF001

    assert client.is_connected is False


def test_only_status_probe_changes_connection_state() -> None:
    client = AiiDAWorkerClient(bridge_url="http://127.0.0.1:8001")

    client._record_status_success("/status")  # noqa: SLF001
    assert client.is_connected is True

    client._record_status_failure("/status")  # noqa: SLF001
    assert client.is_connected is False


@pytest.mark.anyio
async def test_non_status_timeout_keeps_last_confirmed_online_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _TimeoutClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def request(self, *_: object, **__: object):
            raise httpx.TimeoutException("slow detail request")

    client = AiiDAWorkerClient(bridge_url="http://127.0.0.1:8001")
    client._mark_online()  # noqa: SLF001
    client._snapshot.checked_at = time.monotonic()  # noqa: SLF001
    monkeypatch.setattr("src.aris_apps.aiida.client.httpx.AsyncClient", _TimeoutClient)

    with pytest.raises(BridgeAPIError):
        await client.request_json("GET", "/resources", retries=0)

    assert client.is_connected is True


@pytest.mark.anyio
async def test_inspect_infrastructure_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AiiDAWorkerClient(
        bridge_url="http://127.0.0.1:8001",
        infra_cache_ttl_seconds=120.0,
    )
    calls: list[str] = []

    async def _fake_fetch_json(path: str, *, timeout_seconds: float | None = None, retries: int | None = None):
        _ = timeout_seconds, retries
        calls.append(path)
        if path == "/system/info":
            return {
                "profile": "default",
                "daemon_status": True,
                "counts": {"computers": 1, "codes": 2, "workchains": 3},
            }
        if path == "/resources":
            return {
                "computers": [{"label": "localhost"}],
                "codes": [{"label": "pw", "computer_label": "localhost"}],
            }
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr(client, "_fetch_json", _fake_fetch_json)  # type: ignore[method-assign]

    first = await client.inspect_infrastructure()
    second = await client.inspect_infrastructure()

    assert calls == ["/system/info", "/resources"]
    assert first == second
    assert first["profile"] == "default"
    assert first["code_targets"] == ["pw@localhost"]


@pytest.mark.anyio
async def test_get_status_does_not_probe_alternate_plugin_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AiiDAWorkerClient(bridge_url="http://127.0.0.1:8001")
    calls: list[str] = []

    async def _fake_fetch_json(path: str, *, timeout_seconds: float | None = None, retries: int | None = None):
        _ = timeout_seconds, retries
        calls.append(path)
        if path == "/status":
            return {
                "status": "online",
                "mode": "core-injected-executor",
                "environment": "Remote Bridge",
            }
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr(client, "_fetch_json", _fake_fetch_json)  # type: ignore[method-assign]

    snapshot = await client.get_status(force_refresh=True)

    assert snapshot.mode == "core-injected-executor"
    assert snapshot.plugins == []
    assert calls == ["/status"]


@pytest.mark.anyio
async def test_inspect_default_environment_uses_worker_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AiiDAWorkerClient(bridge_url="http://127.0.0.1:8001")

    async def _fake_request_json(method: str, path: str, **kwargs):
        assert method == "GET"
        assert path == "/management/environments/default"
        assert kwargs["params"] == {"force_refresh": True}
        return {
            "success": True,
            "python_interpreter_path": "/tmp/worker-python",
            "plugins": {"calculations": [], "workflows": ["aiida.workflows:core.arithmetic.add"], "data": []},
            "codes": [],
            "computers": [],
        }

    monkeypatch.setattr(client, "request_json", _fake_request_json)
    result = await client.inspect_default_environment(force_refresh=True)

    assert result["success"] is True
    assert result["python_interpreter_path"] == "/tmp/worker-python"


def test_environment_inspect_path_is_not_cached_as_unsupported() -> None:
    client = AiiDAWorkerClient(bridge_url="http://127.0.0.1:8001")

    client._remember_unsupported_path("/management/environments/inspect", 404)  # noqa: SLF001

    assert client._is_path_known_unsupported("/management/environments/inspect") is False  # noqa: SLF001


def test_known_unsupported_prefix_is_cached() -> None:
    client = AiiDAWorkerClient(bridge_url="http://127.0.0.1:8001")

    client._remember_unsupported_path("/management/profiles", 404)  # noqa: SLF001

    assert client._is_path_known_unsupported("/management/profiles") is True  # noqa: SLF001
    assert client._is_path_known_unsupported("/management/profiles/current-user-info") is True  # noqa: SLF001

@pytest.mark.anyio
async def test_get_current_user_info(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AiiDAWorkerClient(bridge_url="http://127.0.0.1:8001")
    user_info = {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john.doe@example.com",
        "institution": "Test Inst",
    }

    async def _fake_fetch_json(path: str, **kwargs):
        assert path == "/management/profiles/current-user-info"
        return user_info

    monkeypatch.setattr(client, "_fetch_json", _fake_fetch_json)
    result = await client.get_current_user_info()
    assert result == user_info


@pytest.mark.anyio
async def test_setup_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AiiDAWorkerClient(bridge_url="http://127.0.0.1:8001")
    payload = {"profile_name": "new_profile"}

    async def _fake_post_json(path: str, payload: dict, **kwargs):
        assert path == "/management/profiles/setup"
        assert payload["profile_name"] == "new_profile"
        return {"status": "success", "profile_name": "new_profile"}

    monkeypatch.setattr(client, "_post_json", _fake_post_json)
    result = await client.setup_profile(payload)
    assert result["status"] == "success"
    assert result["profile_name"] == "new_profile"
