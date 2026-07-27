"""Unified AiiDA worker client.

This module is the single transport/service surface for aiida-worker calls.
It combines low-level JSON request helpers and higher-level bridge snapshot
logic in one singleton-backed class.
"""

from __future__ import annotations

import asyncio
import contextvars
import copy
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping
from urllib.parse import urlparse

import httpx
from loguru import logger

from src.aris_core.logging import log_event
from src.aris_apps.aiida.config import aiida_engine_settings
from .schemas import CodeSetupRequest

DEFAULT_BRIDGE_URL = aiida_engine_settings.default_bridge_url
OFFLINE_WORKER_MESSAGE = aiida_engine_settings.offline_worker_message

BridgeCallListener = Callable[[str], None]
_bridge_call_listener: contextvars.ContextVar[BridgeCallListener | None] = contextvars.ContextVar(
    "aiida_bridge_call_listener",
    default=None,
)
WORKSPACE_PATH_HEADER = "X-ARIS-Active-Workspace-Path"
SESSION_ID_HEADER = "X-ARIS-Session-Id"
PROJECT_ID_HEADER = "X-ARIS-Project-Id"
PYTHON_PATH_HEADER = "X-ARIS-Active-Python-Path"
_bridge_request_headers: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "aiida_bridge_request_headers",
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


def _extract_error_payload(response: httpx.Response) -> tuple[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = response.text

    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, dict):
            message = str(detail.get("error") or detail.get("message") or response.reason_phrase)
        else:
            message = str(payload.get("error") or payload.get("message") or response.reason_phrase)
    else:
        message = str(payload or response.reason_phrase)

    return message, payload


def _normalize_header_entries(headers: Mapping[str, Any] | None = None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    if not headers:
        return normalized
    for key, value in headers.items():
        cleaned_key = str(key or "").strip()
        cleaned_value = str(value or "").strip()
        if cleaned_key and cleaned_value:
            normalized[cleaned_key] = cleaned_value
    return normalized

def build_bridge_context_headers(
    *,
    session_id: Any = None,
    project_id: Any = None,
    workspace_path: Any = None,
    python_path: Any = None,
) -> dict[str, str] | None:
    headers: dict[str, Any] = {}
    if session_id is not None:
        headers[SESSION_ID_HEADER] = session_id
    if project_id is not None:
        headers[PROJECT_ID_HEADER] = project_id
    if workspace_path is not None:
        headers[WORKSPACE_PATH_HEADER] = workspace_path
    if python_path is not None:
        headers[PYTHON_PATH_HEADER] = python_path
    return _normalize_header_entries(headers) or None


def _merge_request_headers(headers: Mapping[str, Any] | None = None) -> dict[str, str] | None:
    merged: dict[str, str] = {}
    scoped_headers = _bridge_request_headers.get()
    for payload in (scoped_headers, headers):
        merged.update(_normalize_header_entries(payload))
    return merged or None


class AiiDAWorkerClient:
    def __init__(
        self,
        bridge_url: str,
        *,
        environment: str = aiida_engine_settings.bridge_environment,
        cache_ttl_seconds: float = 10.0,
        infra_cache_ttl_seconds: float = 8.0,
        request_timeout_seconds: float = 2.0,
        request_retries: int = 2,
        retry_backoff_seconds: float = 0.2,
    ) -> None:
        normalized_url = (bridge_url or aiida_engine_settings.default_bridge_url).strip()
        self._bridge_url = normalized_url.rstrip("/")
        self._environment = environment
        self._cache_ttl_seconds = max(1.0, float(cache_ttl_seconds))
        self._infra_cache_ttl_seconds = max(1.0, float(infra_cache_ttl_seconds))
        self._request_timeout_seconds = max(0.2, float(request_timeout_seconds))
        self._request_retries = max(0, int(request_retries))
        self._retry_backoff_seconds = max(0.05, float(retry_backoff_seconds))

        self._snapshot = BridgeSnapshot(url=self._bridge_url, environment=self._environment)
        self._status_lock = asyncio.Lock()
        self._infrastructure_lock = asyncio.Lock()
        self._infrastructure_cache: dict[str, Any] | None = None
        self._infrastructure_cached_at: float = 0.0
        self._logged_first_handshake = False
        self._unsupported_prefixes: set[str] = set()

    @property
    def bridge_url(self) -> str:
        return self._bridge_url

    @property
    def is_connected(self) -> bool:
        return self._snapshot.status == "online"

    def bridge_endpoint(self, path: str) -> str:
        normalized = path if path.startswith("/") else f"/{path}"
        return f"{self._bridge_url}{normalized}"

    @property
    def worker_mode(self) -> str | None:
        return self._snapshot.mode

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        timeout: float = 10.0,
        retries: int | None = None,
    ) -> Any:
        method_upper = method.upper()
        normalized_path = self._normalize_request_path(path)
        await self._ensure_request_supported_async(normalized_path)
        endpoint = self.bridge_endpoint(path)
        _emit_bridge_call_event(method_upper, path)
        retry_budget = self._resolve_retry_budget(method_upper, retries)
        request_headers = _merge_request_headers(headers)

        for attempt in range(retry_budget + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                    response = await client.request(
                        method_upper,
                        endpoint,
                        params=params,
                        json=json,
                        headers=request_headers,
                    )
            except httpx.ConnectError as exc:
                self._record_status_failure(normalized_path)
                if attempt < retry_budget:
                    await self._sleep_for_retry(attempt)
                    continue
                raise BridgeOfflineError() from exc
            except httpx.TimeoutException as exc:
                self._record_status_failure(normalized_path)
                if attempt < retry_budget:
                    await self._sleep_for_retry(attempt)
                    continue
                raise BridgeAPIError(status_code=0, message=str(exc), payload={"error": str(exc)}) from exc
            except httpx.RequestError as exc:
                self._record_status_failure(normalized_path)
                if attempt < retry_budget:
                    await self._sleep_for_retry(attempt)
                    continue
                raise BridgeAPIError(status_code=0, message=str(exc), payload={"error": str(exc)}) from exc

            if self._should_retry_status(response.status_code) and attempt < retry_budget:
                await self._sleep_for_retry(attempt)
                continue

            if response.status_code >= 400:
                self._remember_unsupported_path(normalized_path, response.status_code)
                message, payload = _extract_error_payload(response)
                raise BridgeAPIError(status_code=response.status_code, message=message, payload=payload)

            self._record_status_success(normalized_path)
            try:
                return response.json()
            except ValueError as exc:
                raise BridgeAPIError(
                    status_code=response.status_code,
                    message="Invalid JSON response",
                    payload=response.text,
                ) from exc

        raise BridgeAPIError(status_code=0, message="Unknown worker request failure", payload={"path": path})

    async def request_multipart(
        self,
        method: str,
        path: str,
        *,
        files: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> Any:
        method_upper = method.upper()
        endpoint = self.bridge_endpoint(path)
        _emit_bridge_call_event(method_upper, path)
        request_headers = _merge_request_headers(headers)

        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.request(
                    method_upper,
                    endpoint,
                    files=files,
                    data=data,
                    headers=request_headers,
                )
        except httpx.ConnectError as exc:
            raise BridgeOfflineError() from exc
        except httpx.RequestError as exc:
            raise BridgeAPIError(status_code=0, message=str(exc), payload={"error": str(exc)}) from exc

        if response.status_code >= 400:
            message, payload = _extract_error_payload(response)
            raise BridgeAPIError(status_code=response.status_code, message=message, payload=payload)

        try:
            return response.json()
        except ValueError as exc:
            raise BridgeAPIError(
                status_code=response.status_code,
                message="Invalid JSON response",
                payload=response.text,
            ) from exc

        raise BridgeAPIError(status_code=0, message="Unknown worker request failure", payload={"path": path})

    def request_json_sync(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        timeout: float = 10.0,
        retries: int | None = None,
    ) -> Any:
        method_upper = method.upper()
        normalized_path = self._normalize_request_path(path)
        self._ensure_request_supported_sync(normalized_path)
        endpoint = self.bridge_endpoint(path)
        _emit_bridge_call_event(method_upper, path)
        retry_budget = self._resolve_retry_budget(method_upper, retries)
        request_headers = _merge_request_headers(headers)

        for attempt in range(retry_budget + 1):
            try:
                with httpx.Client(timeout=timeout, trust_env=False) as client:
                    response = client.request(
                        method_upper,
                        endpoint,
                        params=params,
                        json=json,
                        headers=request_headers,
                    )
            except httpx.ConnectError as exc:
                self._record_status_failure(normalized_path)
                if attempt < retry_budget:
                    self._sleep_for_retry_sync(attempt)
                    continue
                raise BridgeOfflineError() from exc
            except httpx.TimeoutException as exc:
                self._record_status_failure(normalized_path)
                if attempt < retry_budget:
                    self._sleep_for_retry_sync(attempt)
                    continue
                raise BridgeAPIError(status_code=0, message=str(exc), payload={"error": str(exc)}) from exc
            except httpx.RequestError as exc:
                self._record_status_failure(normalized_path)
                if attempt < retry_budget:
                    self._sleep_for_retry_sync(attempt)
                    continue
                raise BridgeAPIError(status_code=0, message=str(exc), payload={"error": str(exc)}) from exc

            if self._should_retry_status(response.status_code) and attempt < retry_budget:
                self._sleep_for_retry_sync(attempt)
                continue

            if response.status_code >= 400:
                self._remember_unsupported_path(normalized_path, response.status_code)
                message, payload = _extract_error_payload(response)
                raise BridgeAPIError(status_code=response.status_code, message=message, payload=payload)

            self._record_status_success(normalized_path)
            try:
                return response.json()
            except ValueError as exc:
                raise BridgeAPIError(
                    status_code=response.status_code,
                    message="Invalid JSON response",
                    payload=response.text,
                ) from exc

        raise BridgeAPIError(status_code=0, message="Unknown worker request failure", payload={"path": path})

    def request_content_sync(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, Any] | None = None,
        timeout: float = 10.0,
        retries: int | None = None,
    ) -> BridgeBinaryResponse:
        method_upper = method.upper()
        endpoint = self.bridge_endpoint(path)
        _emit_bridge_call_event(method_upper, path)
        retry_budget = self._resolve_retry_budget(method_upper, retries)
        request_headers = _merge_request_headers(headers)

        for attempt in range(retry_budget + 1):
            try:
                with httpx.Client(timeout=timeout, trust_env=False) as client:
                    response = client.request(
                        method_upper,
                        endpoint,
                        params=params,
                        json=json,
                        headers=request_headers,
                    )
            except httpx.ConnectError as exc:
                if attempt < retry_budget:
                    self._sleep_for_retry_sync(attempt)
                    continue
                raise BridgeOfflineError() from exc
            except httpx.TimeoutException as exc:
                if attempt < retry_budget:
                    self._sleep_for_retry_sync(attempt)
                    continue
                raise BridgeAPIError(status_code=0, message=str(exc), payload={"error": str(exc)}) from exc
            except httpx.RequestError as exc:
                if attempt < retry_budget:
                    self._sleep_for_retry_sync(attempt)
                    continue
                raise BridgeAPIError(status_code=0, message=str(exc), payload={"error": str(exc)}) from exc

            if self._should_retry_status(response.status_code) and attempt < retry_budget:
                self._sleep_for_retry_sync(attempt)
                continue

            if response.status_code >= 400:
                message, payload = _extract_error_payload(response)
                raise BridgeAPIError(status_code=response.status_code, message=message, payload=payload)

            return BridgeBinaryResponse(
                content=response.content,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type"),
            )

        raise BridgeAPIError(status_code=0, message="Unknown worker request failure", payload={"path": path})

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
        payload = await self._fetch_json("/system/info", timeout_seconds=max(8.0, self._request_timeout_seconds))
        return payload if isinstance(payload, dict) else {}

    async def get_resources(self) -> dict[str, Any]:
        payload = await self._fetch_json("/resources", timeout_seconds=max(8.0, self._request_timeout_seconds))
        return payload if isinstance(payload, dict) else {}

    async def get_profiles(self) -> dict[str, Any]:
        payload = await self._fetch_json("/management/profiles", timeout_seconds=max(8.0, self._request_timeout_seconds))
        if not isinstance(payload, dict):
            return {"current_profile": None, "default_profile": None, "profiles": []}
        return payload

    async def get_current_user_info(self) -> dict[str, Any]:
        payload = await self._fetch_json(
            "/management/profiles/current-user-info",
            timeout_seconds=max(5.0, self._request_timeout_seconds),
        )
        return payload if isinstance(payload, dict) else {}

    async def setup_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post_json(
            "/management/profiles/setup",
            payload=payload,
            timeout_seconds=max(30.0, self._request_timeout_seconds),
        )

    async def switch_profile(self, profile: str) -> dict[str, Any]:
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
        payload = await self._fetch_json("/management/infrastructure", timeout_seconds=max(8.0, self._request_timeout_seconds))
        return payload if isinstance(payload, list) else []

    async def get_infrastructure_capabilities(self) -> dict[str, Any]:
        payload = await self._fetch_json(
            "/management/infrastructure/capabilities",
            timeout_seconds=max(5.0, self._request_timeout_seconds),
        )
        return payload if isinstance(payload, dict) else {}

    async def setup_infrastructure(self, config: dict[str, Any]) -> dict[str, Any]:
        return await self._post_json(
            "/management/infrastructure/setup",
            payload=config,
            timeout_seconds=max(10.0, self._request_timeout_seconds),
        )

    async def setup_code(self, payload: CodeSetupRequest) -> dict[str, Any]:
        """Create a new code on a computer."""
        return await self._post_json(
            "/management/infrastructure/setup-code",
            payload=payload.model_dump(),
            timeout_seconds=max(10.0, self._request_timeout_seconds),
        )

    async def get_computer_codes(self, computer_label: str) -> list[dict[str, Any]]:
        """Fetch detailed codes for a specific computer."""
        payload = await self._fetch_json(
            f"/management/infrastructure/computer/{computer_label}/codes",
            timeout_seconds=max(8.0, self._request_timeout_seconds),
        )
        return payload if isinstance(payload, list) else []

    async def get_ssh_config(self) -> list[dict[str, Any]]:
        """Fetch parsed SSH hosts from ~/.ssh/config via aiida-worker."""
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

        try:
            payload = await self._fetch_json("/status")
        except Exception as error:  # noqa: BLE001
            self._snapshot.status = "offline"
            self._snapshot.checked_at = checked_at
            logger.error(
                log_event(
                    "aiida.bridge.unreachable",
                    url=self._bridge_url,
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
            logger.info(f"[AiiDA Bridge] Connected to worker at {self._worker_target}")
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

    @staticmethod
    def _is_idempotent_method(method: str) -> bool:
        return method.upper() in {"GET", "HEAD", "OPTIONS"}

    @staticmethod
    def _should_retry_status(status_code: int) -> bool:
        return status_code in {408, 425, 429, 500, 502, 503, 504}

    def _resolve_retry_budget(self, method: str, retries: int | None) -> int:
        if retries is not None:
            return max(0, int(retries))
        if self._is_idempotent_method(method):
            return self._request_retries
        return 0

    async def _sleep_for_retry(self, attempt: int) -> None:
        await asyncio.sleep(self._retry_backoff_seconds * float(attempt + 1))

    def _sleep_for_retry_sync(self, attempt: int) -> None:
        time.sleep(self._retry_backoff_seconds * float(attempt + 1))

    def _mark_online(self) -> None:
        self._snapshot.status = "online"

    def _mark_offline(self) -> None:
        self._snapshot.status = "offline"

    def _record_status_success(self, path: str) -> None:
        if path == "/status":
            self._mark_online()

    def _record_status_failure(self, path: str) -> None:
        if path == "/status":
            self._mark_offline()

    @property
    def _worker_target(self) -> str:
        parsed = urlparse(self._bridge_url)
        if parsed.port:
            return f":{parsed.port}"
        if parsed.netloc:
            return parsed.netloc
        return self._bridge_url

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

    def _unsupported_prefix(self, path: str) -> str | None:
        for prefix in (
            "/management/profiles",
            "/management/infrastructure",
            "/management/recent-nodes",
            "/management/recent-processes",
            "/management/groups",
            "/management/nodes",
            "/process/events",
            "/resources",
            "/plugins",
        ):
            if path == prefix or path.startswith(f"{prefix}/"):
                return prefix
        return None

    def _is_path_known_unsupported(self, path: str) -> bool:
        prefix = self._unsupported_prefix(path)
        return prefix in self._unsupported_prefixes if prefix else False

    def _remember_unsupported_path(self, path: str, status_code: int) -> None:
        prefix = self._unsupported_prefix(path)
        if int(status_code) == 404 and prefix:
            self._unsupported_prefixes.add(prefix)

    def _unsupported_endpoint_error(self, path: str) -> BridgeAPIError:
        return BridgeAPIError(
            status_code=404,
            message="Worker endpoint not supported",
            payload={"error": "Worker endpoint not supported by the current worker mode", "path": path},
        )

    async def _ensure_request_supported_async(self, path: str) -> None:
        if path == "/status":
            return
        if self._is_path_known_unsupported(path):
            raise self._unsupported_endpoint_error(path)
        if self._snapshot.checked_at <= 0:
            try:
                await self._refresh_if_needed(force_refresh=False)
            except Exception:
                return

    def _ensure_request_supported_sync(self, path: str) -> None:
        if path == "/status":
            return
        if self._is_path_known_unsupported(path):
            raise self._unsupported_endpoint_error(path)
        if self._snapshot.checked_at <= 0:
            self._probe_status_sync()

    def _probe_status_sync(self) -> None:
        endpoint = self.bridge_endpoint("/status")
        checked_at = time.monotonic()
        try:
            with httpx.Client(timeout=self._request_timeout_seconds, trust_env=False) as client:
                response = client.get(endpoint)
        except Exception:
            return
        if response.status_code >= 400:
            return
        try:
            payload = response.json()
        except ValueError:
            return
        normalized = self._normalize_status_payload(payload)
        self._snapshot.status = normalized["status"]
        self._snapshot.environment = normalized["environment"]
        self._snapshot.mode = normalized["mode"]
        self._snapshot.profile = normalized["profile"]
        self._snapshot.daemon_status = normalized["daemon_status"]
        self._snapshot.resources = normalized["resources"]
        self._snapshot.plugins = normalized["plugins"]
        self._snapshot.checked_at = checked_at

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
                counts.computers = self._count_resource_items(computers)
            if counts.codes == 0:
                counts.codes = self._count_resource_items(codes)

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


def bridge_endpoint(path: str) -> str:
    return aiida_worker_client.bridge_endpoint(path)


def set_bridge_call_listener(
    listener: BridgeCallListener | None,
) -> contextvars.Token[BridgeCallListener | None]:
    return _bridge_call_listener.set(listener)


def reset_bridge_call_listener(token: contextvars.Token[BridgeCallListener | None]) -> None:
    _bridge_call_listener.reset(token)


def set_bridge_request_headers(
    headers: Mapping[str, Any] | None,
) -> contextvars.Token[dict[str, str] | None]:
    normalized_headers = _merge_request_headers(headers)
    return _bridge_request_headers.set(normalized_headers)


def reset_bridge_request_headers(token: contextvars.Token[dict[str, str] | None]) -> None:
    _bridge_request_headers.reset(token)


async def request_json(
    method: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    json: Mapping[str, Any] | None = None,
    headers: Mapping[str, Any] | None = None,
    timeout: float = 10.0,
    retries: int | None = None,
) -> Any:
    return await aiida_worker_client.request_json(
        method,
        path,
        params=params,
        json=json,
        headers=headers,
        timeout=timeout,
        retries=retries,
    )


def request_json_sync(
    method: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    json: Mapping[str, Any] | None = None,
    headers: Mapping[str, Any] | None = None,
    timeout: float = 10.0,
    retries: int | None = None,
) -> Any:
    return aiida_worker_client.request_json_sync(
        method,
        path,
        params=params,
        json=json,
        headers=headers,
        timeout=timeout,
        retries=retries,
    )


def request_content_sync(
    method: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    json: Mapping[str, Any] | None = None,
    headers: Mapping[str, Any] | None = None,
    timeout: float = 10.0,
    retries: int | None = None,
) -> BridgeBinaryResponse:
    return aiida_worker_client.request_content_sync(
        method,
        path,
        params=params,
        json=json,
        headers=headers,
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
    "bridge_endpoint",
    "set_bridge_call_listener",
    "reset_bridge_call_listener",
    "request_json",
    "request_json_sync",
    "format_bridge_error",
]
