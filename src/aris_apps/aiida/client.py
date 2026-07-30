"""Unified AiiDA worker client.

This module is the single transport/service surface for aiida-worker calls.
It combines low-level JSON request helpers and higher-level bridge snapshot
logic in one singleton-backed class.
"""

from __future__ import annotations

import asyncio
import base64
import contextvars
import copy
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping
from urllib.parse import unquote, urlparse

from loguru import logger

from src.aris_core.logging import log_event
from src.aris_core.runtime import WorkerProcessError, get_worker_process_manager
from src.aris_apps.aiida.config import aiida_engine_settings
from .schemas import CodeSetupRequest

DEFAULT_BRIDGE_URL = aiida_engine_settings.default_bridge_url
OFFLINE_WORKER_MESSAGE = aiida_engine_settings.offline_worker_message

BridgeCallListener = Callable[[str], None]
_bridge_call_listener: contextvars.ContextVar[BridgeCallListener | None] = contextvars.ContextVar(
    "aiida_bridge_call_listener",
    default=None,
)
_worker_request_context: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "aiida_worker_request_context",
    default=None,
)

BridgeConnectionState = Literal["online", "offline"]


@dataclass
class BridgeAPIError(Exception):
    status_code: int
    message: str
    payload: Any

    def __str__(self) -> str:
        return f"HTTP {self.status_code}: {self.message}"


class BridgeOfflineError(Exception):
    def __str__(self) -> str:
        return OFFLINE_WORKER_MESSAGE


@dataclass
class BridgeResourceCounts:
    computers: int = 0
    codes: int = 0
    workchains: int = 0


@dataclass
class BridgeBinaryResponse:
    content: bytes
    headers: dict[str, str] = field(default_factory=dict)
    media_type: str | None = None


@dataclass
class BridgeSnapshot:
    status: BridgeConnectionState = "offline"
    url: str = aiida_engine_settings.default_bridge_url
    environment: str = aiida_engine_settings.bridge_environment
    mode: str | None = None
    profile: str = "unknown"
    daemon_status: bool = False
    resources: BridgeResourceCounts = field(default_factory=BridgeResourceCounts)
    plugins: list[str] = field(default_factory=list)
    checked_at: float = 0.0


def _is_identifier_segment(segment: str) -> bool:
    cleaned = segment.strip().lower()
    if not cleaned:
        return False
    if cleaned.isdigit():
        return True
    if len(cleaned) >= 8 and all(char in "0123456789abcdef-" for char in cleaned):
        return True
    return False


def _infer_bridge_call_name(method: str, path: str) -> str:
    parts = [part for part in path.strip("/").split("/") if part]
    normalized_parts = ["{id}" if _is_identifier_segment(part) else part for part in parts]
    compact = ".".join(normalized_parts[-3:]) if normalized_parts else "root"
    return f"{method.upper()} {compact}"


def _emit_bridge_call_event(method: str, path: str) -> None:
    listener = _bridge_call_listener.get()
    if listener is None:
        return
    try:
        listener(_infer_bridge_call_name(method, path))
    except Exception:  # noqa: BLE001
        # Listener errors should never block bridge calls.
        pass


def _normalize_context_entries(context: Mapping[str, Any] | None = None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    if not context:
        return normalized
    allowed = {"session_id", "project_id", "workspace_path", "python_interpreter_path"}
    for key, value in context.items():
        cleaned_key = str(key or "").strip()
        cleaned_value = str(value or "").strip()
        if cleaned_key in allowed and cleaned_value:
            normalized[cleaned_key] = cleaned_value
    return normalized

def build_worker_context(
    *,
    session_id: Any = None,
    project_id: Any = None,
    workspace_path: Any = None,
    python_path: Any = None,
) -> dict[str, str] | None:
    context: dict[str, Any] = {}
    if session_id is not None:
        context["session_id"] = session_id
    if project_id is not None:
        context["project_id"] = project_id
    if workspace_path is not None:
        context["workspace_path"] = workspace_path
    if python_path is not None:
        context["python_interpreter_path"] = python_path
    return _normalize_context_entries(context) or None


def _merge_worker_context(context: Mapping[str, Any] | None = None) -> dict[str, str] | None:
    merged: dict[str, str] = {}
    scoped_context = _worker_request_context.get()
    for payload in (scoped_context, context):
        merged.update(_normalize_context_entries(payload))
    return merged or None


def _run_async_from_sync(coro: Any, timeout: float = 10.0) -> Any:
    manager = get_worker_process_manager()
    loop = manager.loop if manager is not None else None

    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

    if loop is None or not loop.is_running():
        return asyncio.run(coro)

    import concurrent.futures
    import threading

    if threading.current_thread() is not threading.main_thread():
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)

    def _run_in_thread() -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(_run_in_thread).result(timeout=timeout)


def _map_request_to_rpc(
    request_method: str,
    path: str,
    params: Mapping[str, Any] | None = None,
    json: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
) -> tuple[str, dict[str, Any]] | None:
    cleaned_path = str(path or "").strip()
    if cleaned_path.startswith("/"):
        cleaned_path = cleaned_path[1:]

    if "?" in cleaned_path:
        cleaned_path = cleaned_path.split("?", 1)[0]

    parts = [p for p in cleaned_path.split("/") if p]
    req_params: dict[str, Any] = {}
    if params:
        req_params.update(dict(params))
    if json:
        req_params.update(dict(json))
    for field_name, value in (_merge_worker_context(context) or {}).items():
        req_params.setdefault(field_name, value)

    method_upper = request_method.upper()

    if not parts or parts == ["status"]:
        return ("runtime.status", req_params)
    if parts == ["system", "info"]:
        return ("system.info", req_params)
    if parts == ["resources"]:
        return ("resource.summary", req_params)
    if parts == ["plugins"]:
        return ("resource.plugins", req_params)

    if parts and parts[0] == "management":
        sub = parts[1:]
        if sub == ["profiles"]:
            return ("profile.list", req_params)
        if sub == ["profiles", "current-user-info"]:
            return ("profile.current_user", req_params)
        if sub == ["profiles", "setup"]:
            return ("profile.setup", req_params)
        if sub == ["profiles", "switch"]:
            return ("profile.switch", req_params)
        if sub == ["profiles", "load-archive"]:
            return ("profile.load_archive", req_params)
        if sub == ["archives", "local"]:
            return ("archive.list", req_params)
        if sub == ["statistics"]:
            return ("system.statistics", req_params)
        if sub == ["database", "summary"]:
            return ("system.database_summary", req_params)
        if sub == ["environments", "default"]:
            return ("environment.default", req_params)
        if sub == ["environments", "inspect"]:
            return ("environment.inspect", req_params)
        if sub == ["run-python"]:
            return ("execution.run_python", req_params)
        if sub == ["infrastructure"]:
            return ("infrastructure.inspect_v2", req_params)
        if sub == ["infrastructure", "capabilities"]:
            return ("infrastructure.capabilities", req_params)
        if sub == ["infrastructure", "setup"]:
            return ("infrastructure.setup", req_params)
        if sub == ["infrastructure", "setup-code"]:
            return ("infrastructure.setup_code", req_params)
        if sub == ["infrastructure", "test-connection"]:
            return ("infrastructure.test_connection", req_params)
        if sub == ["infrastructure", "ssh-config"]:
            return ("infrastructure.ssh_config", req_params)
        if len(sub) == 5 and sub[:3] == ["infrastructure", "computer", "pk"] and sub[4] == "export":
            req_params["pk"] = int(sub[3])
            return ("infrastructure.export_computer", req_params)
        if len(sub) == 4 and sub[:2] == ["infrastructure", "code"] and sub[3] == "export":
            req_params["pk"] = int(sub[2])
            return ("infrastructure.export_code", req_params)
        if len(sub) == 4 and sub[0] == "infrastructure" and sub[1] == "computer" and sub[3] == "codes":
            req_params["computer_label"] = sub[2]
            return ("infrastructure.computer_codes", req_params)
        if sub == ["groups"]:
            return ("group.list", req_params)
        if sub == ["groups", "labels"]:
            return ("group.labels", req_params)
        if sub == ["groups", "create"]:
            return ("group.create", req_params)
        if len(sub) == 2 and sub[0] == "groups" and sub[1].isdigit():
            req_params["pk"] = int(sub[1])
            if method_upper == "DELETE":
                return ("group.delete", req_params)
        if len(sub) == 2 and sub[0] == "groups":
            req_params["group_name"] = unquote(sub[1])
            return ("group.inspect", req_params)
        if len(sub) == 3 and sub[0] == "groups" and sub[1].isdigit() and sub[2] == "label":
            req_params["pk"] = int(sub[1])
            return ("group.rename", req_params)
        if len(sub) == 3 and sub[0] == "groups" and sub[1].isdigit() and sub[2] == "nodes":
            req_params["pk"] = int(sub[1])
            return ("group.add_nodes", req_params)
        if len(sub) == 4 and sub[0] == "groups" and sub[1].isdigit() and sub[2] == "nodes":
            req_params["pk"] = int(sub[1])
            req_params["node_pk"] = int(sub[3])
            return ("group.remove_node", req_params)
        if len(sub) == 3 and sub[0] == "groups" and sub[1].isdigit() and sub[2] == "export":
            req_params["pk"] = int(sub[1])
            return ("group.export_archive", req_params)
        if sub == ["recent-nodes"]:
            return ("node.recent", req_params)
        if sub == ["recent-processes"]:
            return ("process.recent", req_params)
        if sub == ["nodes", "context"]:
            return ("node.context", req_params)
        if len(sub) == 3 and sub[0] == "nodes" and sub[1].isdigit() and sub[2] == "soft-delete":
            req_params["pk"] = int(sub[1])
            return ("node.soft_delete", req_params)
        if len(sub) == 3 and sub[0] == "nodes" and sub[1].isdigit() and sub[2] == "script":
            req_params["pk"] = int(sub[1])
            return ("node.script", req_params)
        if len(sub) == 2 and sub[0] == "nodes" and sub[1].isdigit():
            req_params["pk"] = int(sub[1])
            return ("node.summary", req_params)
        if sub == ["source-map"]:
            return ("source_map", req_params)

    if parts and parts[0] == "submission":
        sub = parts[1:]
        if len(sub) == 2 and sub[0] == "spec":
            req_params["entry_point"] = sub[1]
            return ("submission.spec", req_params)
        if sub == ["validate"]:
            return ("submission.validate", req_params)
        if sub == ["draft-builder"] or sub == ["builder-draft"]:
            return ("submission.builder_draft", req_params)
        if sub == ["submit"]:
            return ("submission.submit", req_params)
        if sub == ["workgraph", "submit"]:
            return ("submission.workgraph.submit", req_params)

    if parts and parts[0] == "process":
        sub = parts[1:]
        if len(sub) == 1:
            req_params["identifier"] = sub[0]
            return ("process.detail", req_params)
        if len(sub) == 2 and sub[1] == "workgraph":
            req_params["identifier"] = sub[0]
            return ("process.workgraph", req_params)
        if len(sub) == 2 and sub[1] == "logs":
            req_params["identifier"] = sub[0]
            return ("process.logs", req_params)
        if len(sub) == 2 and sub[1] == "clone-draft":
            req_params["identifier"] = sub[0]
            return ("process.clone_draft", req_params)

    if parts and parts[0] == "registry":
        if parts[1:] == ["list"]:
            return ("registry.list", req_params)
        if parts[1:] == ["register"]:
            return ("registry.register", req_params)

    if len(parts) == 2 and parts[0] == "execute":
        req_params["script_name"] = unquote(parts[1])
        return ("registry.execute", req_params)

    if parts and parts[0] == "data":
        sub = parts[1:]
        if len(sub) == 2 and sub[0] == "node":
            req_params["pk"] = int(sub[1])
            return ("node.summary", req_params)
        if len(sub) == 2 and sub[0] == "bands":
            req_params["pk"] = int(sub[1])
            return ("data.bands", req_params)
        if len(sub) == 3 and sub[0] == "remote" and sub[2] == "files":
            req_params["pk"] = int(sub[1])
            return ("data.remote_files", req_params)
        if len(sub) >= 4 and sub[0] == "remote" and sub[2] == "files":
            req_params["pk"] = int(sub[1])
            req_params["filename"] = unquote("/".join(sub[3:]))
            return ("data.remote_file", req_params)
        if len(sub) == 3 and sub[0] == "repository" and sub[2] == "files":
            req_params["pk"] = int(sub[1])
            return ("data.repository_files", req_params)
        if len(sub) >= 4 and sub[0] == "repository" and sub[2] == "files":
            req_params["pk"] = int(sub[1])
            req_params["filename"] = unquote("/".join(sub[3:]))
            return ("data.repository_file", req_params)
        if len(sub) == 2 and sub[0] == "import":
            req_params["data_type"] = unquote(sub[1])
            return ("data.import", req_params)

    return None


class AiiDAWorkerClient:
    def __init__(
        self,
        bridge_url: str,
        *,
        environment: str = aiida_engine_settings.bridge_environment,
        cache_ttl_seconds: float = 10.0,
        infra_cache_ttl_seconds: float = 8.0,
        request_timeout_seconds: float = 2.0,
    ) -> None:
        normalized_url = (bridge_url or aiida_engine_settings.default_bridge_url).strip()
        self._bridge_url = normalized_url.rstrip("/")
        self._environment = environment
        self._cache_ttl_seconds = max(1.0, float(cache_ttl_seconds))
        self._infra_cache_ttl_seconds = max(1.0, float(infra_cache_ttl_seconds))
        self._request_timeout_seconds = max(0.2, float(request_timeout_seconds))

        self._snapshot = BridgeSnapshot(url=self._bridge_url, environment=self._environment)
        self._status_lock = asyncio.Lock()
        self._infrastructure_lock = asyncio.Lock()
        self._infrastructure_cache: dict[str, Any] | None = None
        self._infrastructure_cached_at: float = 0.0
        self._logged_first_handshake = False

    @property
    def bridge_url(self) -> str:
        return self._bridge_url

    @property
    def is_connected(self) -> bool:
        return self._snapshot.status == "online"

    @property
    def worker_mode(self) -> str | None:
        return self._snapshot.mode

    @staticmethod
    def _bridge_error_from_worker(exc: WorkerProcessError) -> BridgeAPIError:
        return BridgeAPIError(
            status_code=exc.status_code,
            message=exc.message,
            payload=exc.payload,
        )

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        timeout: float = 10.0,
        retries: int | None = None,
    ) -> Any:
        method_upper = method.upper()
        manager = get_worker_process_manager()
        if manager is None:
            raise BridgeOfflineError()
        rpc_target = _map_request_to_rpc(method, path, params=params, json=json, context=context)
        if rpc_target is None:
            raise self._unsupported_endpoint_error(self._normalize_request_path(path))
        rpc_method, rpc_params = rpc_target
        _emit_bridge_call_event(method_upper, path)
        try:
            result = await manager.request(rpc_method, rpc_params, timeout=timeout)
        except WorkerProcessError as exc:
            raise self._bridge_error_from_worker(exc) from exc
        self._record_status_success(self._normalize_request_path(path))
        return result

    async def request_multipart(
        self,
        method: str,
        path: str,
        *,
        files: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> Any:
        rpc_target = _map_request_to_rpc(method, path, params=data, context=context)
        if rpc_target is None or rpc_target[0] != "data.import":
            raise self._unsupported_endpoint_error(self._normalize_request_path(path))
        rpc_method, rpc_params = rpc_target
        file_value = (files or {}).get("file")
        if file_value is not None:
            if not isinstance(file_value, (tuple, list)) or len(file_value) < 2:
                raise BridgeAPIError(
                    status_code=422,
                    message="Invalid file payload",
                    payload={"error": "Expected (filename, bytes, content_type)"},
                )
            filename, content = file_value[0], file_value[1]
            if hasattr(content, "read"):
                content = content.read()
                if asyncio.iscoroutine(content):
                    content = await content
            if not isinstance(content, (bytes, bytearray)):
                raise BridgeAPIError(
                    status_code=422,
                    message="Invalid file content",
                    payload={"error": "Uploaded file content must be bytes"},
                )
            rpc_params["filename"] = str(filename or "uploaded_file")
            rpc_params["content_base64"] = base64.b64encode(bytes(content)).decode("ascii")
        manager = get_worker_process_manager()
        if manager is None:
            raise BridgeOfflineError()
        _emit_bridge_call_event(method.upper(), path)
        try:
            return await manager.request(rpc_method, rpc_params, timeout=timeout)
        except WorkerProcessError as exc:
            raise self._bridge_error_from_worker(exc) from exc

    def request_json_sync(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        timeout: float = 10.0,
        retries: int | None = None,
    ) -> Any:
        method_upper = method.upper()
        manager = get_worker_process_manager()
        if manager is None:
            raise BridgeOfflineError()
        rpc_target = _map_request_to_rpc(method, path, params=params, json=json, context=context)
        if rpc_target is None:
            raise self._unsupported_endpoint_error(self._normalize_request_path(path))
        rpc_method, rpc_params = rpc_target
        _emit_bridge_call_event(method_upper, path)
        try:
            result = _run_async_from_sync(
                manager.request(rpc_method, rpc_params, timeout=timeout),
                timeout=timeout,
            )
        except WorkerProcessError as exc:
            raise self._bridge_error_from_worker(exc) from exc
        self._record_status_success(self._normalize_request_path(path))
        return result

    def request_content_sync(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        timeout: float = 10.0,
        retries: int | None = None,
    ) -> BridgeBinaryResponse:
        payload = self.request_json_sync(
            method,
            path,
            params=params,
            json=json,
            context=context,
            timeout=timeout,
            retries=retries,
        )
        if not isinstance(payload, dict):
            raise BridgeAPIError(500, "Invalid binary response", {"error": "Worker result must be an object"})
        encoded = payload.get("content_base64")
        if not isinstance(encoded, str):
            raise BridgeAPIError(500, "Invalid binary response", payload)
        try:
            content = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise BridgeAPIError(500, "Invalid binary response", payload) from exc
        filename = str(payload.get("filename") or "archive.aiida")
        media_type = str(payload.get("media_type") or "application/octet-stream")
        return BridgeBinaryResponse(
            content=content,
            headers={"content-type": media_type, "content-disposition": f'attachment; filename="{filename}"'},
            media_type=media_type,
        )

    async def get_status(self, *, force_refresh: bool = False) -> BridgeSnapshot:
        await self._refresh_if_needed(force_refresh=force_refresh)
        return BridgeSnapshot(
            status=self._snapshot.status,
            url=self._snapshot.url,
            environment=self._snapshot.environment,
            mode=self._snapshot.mode,
            profile=self._snapshot.profile,
            daemon_status=self._snapshot.daemon_status,
            resources=BridgeResourceCounts(
                computers=self._snapshot.resources.computers,
                codes=self._snapshot.resources.codes,
                workchains=self._snapshot.resources.workchains,
            ),
            plugins=list(self._snapshot.plugins),
            checked_at=self._snapshot.checked_at,
        )

    async def get_plugins(self, *, force_refresh: bool = False) -> list[str]:
        snapshot = await self.get_status(force_refresh=force_refresh)
        return snapshot.plugins

    async def get_system_info(self) -> dict[str, Any]:
        manager = get_worker_process_manager()
        if manager is not None and manager.is_running:
            return await manager.request("system.info", {})
        payload = await self._fetch_json("/system/info", timeout_seconds=max(8.0, self._request_timeout_seconds))
        return payload if isinstance(payload, dict) else {}

    async def get_resources(self) -> dict[str, Any]:
        payload = await self._fetch_json("/resources", timeout_seconds=max(8.0, self._request_timeout_seconds))
        return payload if isinstance(payload, dict) else {}

    async def get_profiles(self) -> dict[str, Any]:
        manager = get_worker_process_manager()
        if manager is not None and manager.is_running:
            return await manager.request("profile.list", {})
        payload = await self._fetch_json("/management/profiles", timeout_seconds=max(8.0, self._request_timeout_seconds))
        if not isinstance(payload, dict):
            return {"current_profile": None, "default_profile": None, "profiles": []}
        return payload

    async def get_current_user_info(self) -> dict[str, Any]:
        manager = get_worker_process_manager()
        if manager is not None and manager.is_running:
            return await manager.request("profile.current_user", {})
        payload = await self._fetch_json(
            "/management/profiles/current-user-info",
            timeout_seconds=max(5.0, self._request_timeout_seconds),
        )
        return payload if isinstance(payload, dict) else {}

    async def setup_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        manager = get_worker_process_manager()
        if manager is not None and manager.is_running:
            return await manager.request("profile.setup", payload, timeout=30.0)
        return await self._post_json(
            "/management/profiles/setup",
            payload=payload,
            timeout_seconds=max(30.0, self._request_timeout_seconds),
        )

    async def switch_profile(self, profile: str) -> dict[str, Any]:
        manager = get_worker_process_manager()
        if manager is not None and manager.is_running:
            res = await manager.request("profile.switch", {"profile": profile}, timeout=8.0)
            await self.get_status(force_refresh=True)
            return res
        payload = await self._post_json(
            "/management/profiles/switch",
            payload={"profile": profile},
            timeout_seconds=max(8.0, self._request_timeout_seconds),
            retries=0,
        )
        await self.get_status(force_refresh=True)
        if not isinstance(payload, dict):
            return {"status": "switched", "current_profile": profile}
        return payload

    async def inspect_infrastructure(self, *, force_refresh: bool = False) -> dict[str, Any]:
        if not force_refresh and self._is_infrastructure_cache_fresh():
            return copy.deepcopy(self._infrastructure_cache or {})

        async with self._infrastructure_lock:
            if not force_refresh and self._is_infrastructure_cache_fresh():
                return copy.deepcopy(self._infrastructure_cache or {})

            system_payload = await self.get_system_info()
            resources_payload = await self.get_resources()
            if not isinstance(system_payload, dict) or not isinstance(resources_payload, dict):
                raise BridgeAPIError(
                    status_code=0,
                    message="Bridge returned invalid infrastructure payload",
                    payload={"system": system_payload, "resources": resources_payload},
                )

            computers = resources_payload.get("computers") if isinstance(resources_payload.get("computers"), list) else []
            codes = resources_payload.get("codes") if isinstance(resources_payload.get("codes"), list) else []
            payload = {
                "profile": str(system_payload.get("profile") or "unknown"),
                "daemon_status": bool(system_payload.get("daemon_status", False)),
                "counts": system_payload.get("counts") if isinstance(system_payload.get("counts"), dict) else {},
                "computers": computers,
                "codes": codes,
                "code_targets": [
                    f"{code.get('label')}@{code.get('computer_label')}"
                    if isinstance(code, dict) and code.get("computer_label")
                    else str(code.get("label") if isinstance(code, dict) else code)
                    for code in codes
                ],
            }
            self._infrastructure_cache = payload
            self._infrastructure_cached_at = time.monotonic()
            return copy.deepcopy(payload)

    async def inspect_default_environment(self, *, force_refresh: bool = False) -> dict[str, Any]:
        payload = await self.request_json(
            "GET",
            "/management/environments/default",
            params={"force_refresh": bool(force_refresh)},
            timeout=max(8.0, self._request_timeout_seconds),
            retries=0,
        )
        return payload if isinstance(payload, dict) else {}

    async def inspect_infrastructure_v2(self) -> list[dict[str, Any]]:
        """Fetch nested infrastructure (Computers -> Codes)."""
        manager = get_worker_process_manager()
        if manager is not None and manager.is_running:
            res = await manager.request("infrastructure.inspect_v2", {})
            infra = res.get("infrastructure")
            return infra if isinstance(infra, list) else []
        payload = await self._fetch_json("/management/infrastructure", timeout_seconds=max(8.0, self._request_timeout_seconds))
        return payload if isinstance(payload, list) else []

    async def get_infrastructure_capabilities(self) -> dict[str, Any]:
        manager = get_worker_process_manager()
        if manager is not None and manager.is_running:
            return await manager.request("infrastructure.capabilities", {})
        payload = await self._fetch_json(
            "/management/infrastructure/capabilities",
            timeout_seconds=max(5.0, self._request_timeout_seconds),
        )
        return payload if isinstance(payload, dict) else {}

    async def setup_infrastructure(self, config: dict[str, Any]) -> dict[str, Any]:
        manager = get_worker_process_manager()
        if manager is not None and manager.is_running:
            return await manager.request("infrastructure.setup", config, timeout=10.0)
        return await self._post_json(
            "/management/infrastructure/setup",
            payload=config,
            timeout_seconds=max(10.0, self._request_timeout_seconds),
        )

    async def setup_code(self, payload: CodeSetupRequest) -> dict[str, Any]:
        """Create a new code on a computer."""
        manager = get_worker_process_manager()
        if manager is not None and manager.is_running:
            return await manager.request("infrastructure.setup_code", payload.model_dump(), timeout=10.0)
        return await self._post_json(
            "/management/infrastructure/setup-code",
            payload=payload.model_dump(),
            timeout_seconds=max(10.0, self._request_timeout_seconds),
        )

    async def get_computer_codes(self, computer_label: str) -> list[dict[str, Any]]:
        """Fetch detailed codes for a specific computer."""
        manager = get_worker_process_manager()
        if manager is not None and manager.is_running:
            res = await manager.request("infrastructure.computer_codes", {"computer_label": computer_label})
            codes = res.get("codes")
            return codes if isinstance(codes, list) else []
        payload = await self._fetch_json(
            f"/management/infrastructure/computer/{computer_label}/codes",
            timeout_seconds=max(8.0, self._request_timeout_seconds),
        )
        return payload if isinstance(payload, list) else []

    async def get_ssh_config(self) -> list[dict[str, Any]]:
        """Fetch parsed SSH hosts from ~/.ssh/config via aiida-worker."""
        manager = get_worker_process_manager()
        if manager is not None and manager.is_running:
            res = await manager.request("infrastructure.ssh_config", {})
            return res.get("hosts", []) if isinstance(res, dict) else []
        payload = await self._fetch_json(
            "/management/infrastructure/ssh-config",
            timeout_seconds=max(5.0, self._request_timeout_seconds),
        )
        return payload if isinstance(payload, list) else []

    async def _refresh_if_needed(self, *, force_refresh: bool) -> None:
        if not force_refresh and self._is_cache_fresh():
            return

        async with self._status_lock:
            if not force_refresh and self._is_cache_fresh():
                return
            await self._refresh_locked()

    def _is_cache_fresh(self) -> bool:
        checked_at = self._snapshot.checked_at
        if checked_at <= 0:
            return False
        return (time.monotonic() - checked_at) < self._cache_ttl_seconds

    def _is_infrastructure_cache_fresh(self) -> bool:
        if self._infrastructure_cache is None or self._infrastructure_cached_at <= 0:
            return False
        return (time.monotonic() - self._infrastructure_cached_at) < self._infra_cache_ttl_seconds

    async def _refresh_locked(self) -> None:
        checked_at = time.monotonic()

        manager = get_worker_process_manager()
        if manager is None:
            self._snapshot.status = "offline"
            self._snapshot.checked_at = checked_at
            return
        try:
            payload = await manager.request("runtime.status", {})
        except Exception as error:  # noqa: BLE001
            self._snapshot.status = "offline"
            self._snapshot.checked_at = checked_at
            logger.error(
                log_event(
                    "aiida.worker.unreachable",
                    transport="stdio-jsonrpc",
                    error=f"{type(error).__name__}: {error}",
                )
            )
            return

        normalized = self._normalize_status_payload(payload)
        self._snapshot.status = normalized["status"]
        self._snapshot.checked_at = checked_at
        if normalized["status"] == "online":
            if normalized["resources"].workchains == 0 and normalized["plugins"]:
                normalized["resources"].workchains = len(normalized["plugins"])
            self._snapshot.environment = normalized["environment"]
            self._snapshot.mode = normalized["mode"]
            self._snapshot.profile = normalized["profile"]
            self._snapshot.daemon_status = normalized["daemon_status"]
            self._snapshot.resources = normalized["resources"]
            self._snapshot.plugins = normalized["plugins"]

        if not self._logged_first_handshake:
            logger.info("[AiiDA Worker] Connected over managed stdio JSON-RPC")
            self._logged_first_handshake = True

    async def _fetch_json(
        self,
        path: str,
        *,
        timeout_seconds: float | None = None,
        retries: int | None = None,
    ) -> Any:
        return await self.request_json(
            "GET",
            path,
            timeout=timeout_seconds or self._request_timeout_seconds,
            retries=retries,
        )

    async def _post_json(
        self,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
        retries: int | None = 0,
    ) -> Any:
        return await self.request_json(
            "POST",
            path,
            json=payload or {},
            timeout=timeout_seconds or self._request_timeout_seconds,
            retries=retries,
        )

    def _mark_online(self) -> None:
        self._snapshot.status = "online"

    def _mark_offline(self) -> None:
        self._snapshot.status = "offline"

    def _record_status_success(self, path: str) -> None:
        if path == "/status":
            self._mark_online()

    def _normalize_status_payload(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {
                "status": "online",
                "environment": self._environment,
                "mode": None,
                "profile": "unknown",
                "daemon_status": False,
                "resources": BridgeResourceCounts(),
                "plugins": [],
            }

        raw_status = str(payload.get("status") or "online").strip().lower()
        status: BridgeConnectionState = "offline" if raw_status in {
            "offline",
            "error",
            "failed",
            "unavailable",
        } else "online"

        environment = self._extract_first_non_empty(payload, ("environment", "worker_environment"))
        mode = self._extract_first_non_empty(payload, ("mode", "worker_mode"))
        profile = self._extract_profile(payload)
        daemon_status = self._extract_daemon_status(payload)
        resources = self._extract_resource_counts(payload)
        plugins = self._extract_plugins(payload)

        return {
            "status": status,
            "environment": environment or self._environment,
            "mode": mode,
            "profile": profile or "unknown",
            "daemon_status": daemon_status,
            "resources": resources,
            "plugins": plugins,
        }

    def _normalize_request_path(self, path: str) -> str:
        cleaned = str(path or "").strip() or "/"
        parsed = urlparse(cleaned)
        normalized = parsed.path or "/"
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        return normalized

    def _unsupported_endpoint_error(self, path: str) -> BridgeAPIError:
        return BridgeAPIError(
            status_code=404,
            message="Worker endpoint not supported",
            payload={"error": "Worker capability is not mapped to the stdio protocol", "path": path},
        )

    def _extract_profile(self, payload: dict[str, Any]) -> str | None:
        profile = self._extract_first_non_empty(payload, ("profile", "current_profile", "active_profile"))
        if profile:
            return profile

        system = payload.get("system")
        if isinstance(system, dict):
            nested = self._extract_first_non_empty(system, ("profile", "current_profile", "active_profile"))
            if nested:
                return nested
        return None

    def _extract_daemon_status(self, payload: dict[str, Any]) -> bool:
        for key in ("daemon_status", "daemon_running", "is_daemon_running"):
            value = payload.get(key)
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "yes", "on", "running"}:
                    return True
                if lowered in {"false", "no", "off", "stopped"}:
                    return False
        return False

    def _extract_resource_counts(self, payload: dict[str, Any]) -> BridgeResourceCounts:
        counts = BridgeResourceCounts()

        counts_payload = payload.get("counts")
        if isinstance(counts_payload, dict):
            counts.computers = self._coerce_non_negative_int(counts_payload.get("computers"))
            counts.codes = self._coerce_non_negative_int(counts_payload.get("codes"))
            counts.workchains = self._coerce_non_negative_int(counts_payload.get("workchains"))

        resources_payload = payload.get("resources")
        if isinstance(resources_payload, dict):
            computers = resources_payload.get("computers")
            codes = resources_payload.get("codes")
            if counts.computers == 0:
                counts.computers = (
                    self._coerce_non_negative_int(computers)
                    if isinstance(computers, (int, str))
                    else self._count_resource_items(computers)
                )
            if counts.codes == 0:
                counts.codes = (
                    self._coerce_non_negative_int(codes)
                    if isinstance(codes, (int, str))
                    else self._count_resource_items(codes)
                )
            if counts.workchains == 0:
                workchains = resources_payload.get("workchains")
                counts.workchains = (
                    self._coerce_non_negative_int(workchains)
                    if isinstance(workchains, (int, str))
                    else self._count_resource_items(workchains)
                )

        if counts.workchains == 0:
            workchains = payload.get("workchains")
            counts.workchains = self._count_resource_items(workchains)
        if counts.workchains == 0:
            counts.workchains = self._coerce_non_negative_int(payload.get("plugin_count"))

        return counts

    def _extract_plugins(self, payload: dict[str, Any]) -> list[str]:
        for key in ("plugins", "plugin_names", "workchains"):
            raw = payload.get(key)
            normalized = self._normalize_plugins(raw)
            if normalized:
                return normalized

        resources_payload = payload.get("resources")
        if isinstance(resources_payload, dict):
            normalized = self._normalize_plugins(resources_payload.get("plugins"))
            if normalized:
                return normalized
        return []

    @staticmethod
    def _count_resource_items(value: Any) -> int:
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return len(value)
        return 0

    @staticmethod
    def _coerce_non_negative_int(value: Any) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return max(0, parsed)

    @staticmethod
    def _extract_first_non_empty(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _normalize_plugins(self, payload: Any) -> list[str]:
        raw_plugins: list[Any]
        if isinstance(payload, list):
            raw_plugins = payload
        elif isinstance(payload, dict):
            raw_plugins = []
            for key in (
                "plugins",
                "items",
                "workchains",
                "plugin_names",
                "entry_points",
                "entries",
                "available_plugins",
                "available_workchains",
            ):
                candidate = payload.get(key)
                if isinstance(candidate, list):
                    raw_plugins = candidate
                    break

            if not raw_plugins:
                for key in ("data", "result", "payload", "response"):
                    nested = payload.get(key)
                    normalized_nested = self._normalize_plugins(nested)
                    if normalized_nested:
                        return normalized_nested

            if not raw_plugins:
                values = list(payload.values())
                if any(isinstance(value, dict) and any(k in value for k in ("name", "entry_point", "plugin", "id")) for value in values):
                    raw_plugins = values

            if not raw_plugins:
                ignored_keys = {
                    "status",
                    "message",
                    "detail",
                    "error",
                    "count",
                    "total",
                    "data",
                    "result",
                    "payload",
                    "response",
                }
                mapping_keys = [
                    key
                    for key in payload.keys()
                    if isinstance(key, str) and key not in ignored_keys and (":" in key or "." in key)
                ]
                if mapping_keys:
                    raw_plugins = mapping_keys
        else:
            raw_plugins = []

        normalized: list[str] = []
        seen: set[str] = set()
        for item in raw_plugins:
            plugin_name = self._normalize_plugin_item(item)
            if not plugin_name or plugin_name in seen:
                continue
            seen.add(plugin_name)
            normalized.append(plugin_name)

        normalized.sort()
        return normalized

    @staticmethod
    def _normalize_plugin_item(item: Any) -> str:
        if isinstance(item, str):
            return item.strip()

        if isinstance(item, dict):
            for key in ("name", "entry_point", "plugin", "id"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return str(item).strip()

        return str(item).strip()


_aiida_worker_client: AiiDAWorkerClient | None = None


def get_aiida_worker_client() -> AiiDAWorkerClient:
    global _aiida_worker_client
    if _aiida_worker_client is None:
        _aiida_worker_client = AiiDAWorkerClient(
            bridge_url=aiida_engine_settings.resolved_bridge_url,
            environment=aiida_engine_settings.bridge_environment,
        )
    return _aiida_worker_client


aiida_worker_client = get_aiida_worker_client()


def bridge_url() -> str:
    return aiida_worker_client.bridge_url


def set_bridge_call_listener(
    listener: BridgeCallListener | None,
) -> contextvars.Token[BridgeCallListener | None]:
    return _bridge_call_listener.set(listener)


def reset_bridge_call_listener(token: contextvars.Token[BridgeCallListener | None]) -> None:
    _bridge_call_listener.reset(token)


def set_worker_request_context(
    context: Mapping[str, Any] | None,
) -> contextvars.Token[dict[str, str] | None]:
    normalized_context = _merge_worker_context(context)
    return _worker_request_context.set(normalized_context)


def reset_worker_request_context(token: contextvars.Token[dict[str, str] | None]) -> None:
    _worker_request_context.reset(token)


async def request_json(
    method: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    json: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    timeout: float = 10.0,
    retries: int | None = None,
) -> Any:
    return await aiida_worker_client.request_json(
        method,
        path,
        params=params,
        json=json,
        context=context,
        timeout=timeout,
        retries=retries,
    )


def request_json_sync(
    method: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    json: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    timeout: float = 10.0,
    retries: int | None = None,
) -> Any:
    return aiida_worker_client.request_json_sync(
        method,
        path,
        params=params,
        json=json,
        context=context,
        timeout=timeout,
        retries=retries,
    )


def request_content_sync(
    method: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    json: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    timeout: float = 10.0,
    retries: int | None = None,
) -> BridgeBinaryResponse:
    return aiida_worker_client.request_content_sync(
        method,
        path,
        params=params,
        json=json,
        context=context,
        timeout=timeout,
        retries=retries,
    )


def format_bridge_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, BridgeOfflineError):
        return {"error": OFFLINE_WORKER_MESSAGE}
    if isinstance(exc, BridgeAPIError):
        return {
            "error": exc.message,
            "status_code": exc.status_code,
            "details": exc.payload,
        }
    return {"error": str(exc)}


__all__ = [
    "DEFAULT_BRIDGE_URL",
    "OFFLINE_WORKER_MESSAGE",
    "BridgeAPIError",
    "BridgeCallListener",
    "BridgeOfflineError",
    "BridgeConnectionState",
    "BridgeResourceCounts",
    "BridgeSnapshot",
    "AiiDAWorkerClient",
    "get_aiida_worker_client",
    "aiida_worker_client",
    "bridge_url",
    "set_bridge_call_listener",
    "reset_bridge_call_listener",
    "request_json",
    "request_json_sync",
    "format_bridge_error",
]
