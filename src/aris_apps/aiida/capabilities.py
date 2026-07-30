"""Application-facing AiiDA capability boundary."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote

from src.aris_apps.aiida.client import AiiDAWorkerClient, WorkerSnapshot, aiida_worker_client


@runtime_checkable
class AiiDACapability(Protocol):
    """Deterministic AiiDA operations consumed by the ARIS application."""

    @property
    def bridge_url(self) -> str: ...

    async def get_status(self) -> WorkerSnapshot: ...

    async def get_plugins(self) -> list[str]: ...

    async def get_resources(self) -> dict[str, Any]: ...

    async def get_profiles(self) -> dict[str, Any]: ...

    async def switch_profile(self, profile: str) -> dict[str, Any]: ...

    async def get_system_info(self) -> dict[str, Any]: ...

    async def list_recent_processes(
        self,
        *,
        limit: int = 20,
    ) -> dict[str, Any]: ...

    async def inspect_process(self, identifier: str) -> dict[str, Any]: ...

    async def get_process_logs(self, pk: int) -> dict[str, Any]: ...

    async def list_recent_nodes(
        self,
        *,
        limit: int = 50,
        node_type: str | None = None,
    ) -> dict[str, Any]: ...

    async def list_submission_plugins(self) -> dict[str, Any]: ...

    async def get_submission_spec(
        self,
        workchain: str,
    ) -> dict[str, Any]: ...

    async def build_submission_draft(
        self,
        request: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def validate_submission_draft(
        self,
        draft: dict[str, Any],
    ) -> dict[str, Any]: ...


class ManagedAiiDACapability:
    """Adapter backed by ARIS' managed aiida-worker subprocess."""

    def __init__(self, client: AiiDAWorkerClient) -> None:
        self._client = client

    @property
    def bridge_url(self) -> str:
        return self._client.bridge_url

    async def get_status(self) -> WorkerSnapshot:
        return await self._client.get_status()

    async def get_plugins(self) -> list[str]:
        return await self._client.get_plugins()

    async def get_resources(self) -> dict[str, Any]:
        return await self._client.get_resources()

    async def get_profiles(self) -> dict[str, Any]:
        return await self._client.get_profiles()

    async def switch_profile(self, profile: str) -> dict[str, Any]:
        return await self._client.switch_profile(profile)

    async def get_system_info(self) -> dict[str, Any]:
        return await self._client.get_system_info()

    async def list_recent_processes(
        self,
        *,
        limit: int = 20,
    ) -> dict[str, Any]:
        payload = await self._client.worker_call(
            "GET",
            "/management/recent-processes",
            params={"limit": int(limit)},
        )
        return payload if isinstance(payload, dict) else {"processes": []}

    async def inspect_process(self, identifier: str) -> dict[str, Any]:
        cleaned = str(identifier or "").strip()
        if not cleaned:
            raise ValueError("Process identifier is required")
        payload = await self._client.worker_call(
            "GET",
            f"/process/{quote(cleaned, safe='')}",
        )
        return payload if isinstance(payload, dict) else {}

    async def get_process_logs(self, pk: int) -> dict[str, Any]:
        payload = await self._client.worker_call(
            "GET",
            f"/process/{int(pk)}/logs",
        )
        return payload if isinstance(payload, dict) else {"logs": []}

    async def list_recent_nodes(
        self,
        *,
        limit: int = 50,
        node_type: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": int(limit)}
        cleaned_node_type = str(node_type or "").strip()
        if cleaned_node_type:
            params["node_type"] = cleaned_node_type
        payload = await self._client.worker_call(
            "GET",
            "/management/recent-nodes",
            params=params,
        )
        return payload if isinstance(payload, dict) else {"nodes": []}

    async def list_submission_plugins(self) -> dict[str, Any]:
        payload = await self._client.worker_call(
            "GET",
            "/plugins",
        )
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list):
            return {"plugins": [str(item) for item in payload if str(item).strip()]}
        return {"plugins": []}

    async def get_submission_spec(
        self,
        workchain: str,
    ) -> dict[str, Any]:
        cleaned = str(workchain or "").strip()
        if not cleaned:
            raise ValueError("WorkChain entry point is required")
        payload = await self._client.worker_call(
            "GET",
            f"/submission/spec/{quote(cleaned, safe='')}",
        )
        return payload if isinstance(payload, dict) else {}

    async def build_submission_draft(
        self,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        payload = await self._client.worker_call(
            "POST",
            "/submission/draft-builder",
            json=dict(request),
            retries=0,
        )
        return payload if isinstance(payload, dict) else {}

    async def validate_submission_draft(
        self,
        draft: dict[str, Any],
    ) -> dict[str, Any]:
        payload = await self._client.worker_call(
            "POST",
            "/submission/validate",
            json={"draft": dict(draft)},
            retries=0,
        )
        return payload if isinstance(payload, dict) else {}


aiida_capability: AiiDACapability = ManagedAiiDACapability(aiida_worker_client)


__all__ = ["AiiDACapability", "ManagedAiiDACapability", "aiida_capability"]
