"""Application-facing AiiDA capability boundary."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.aris_apps.aiida.client import AiiDAWorkerClient, BridgeSnapshot, aiida_worker_client


@runtime_checkable
class AiiDACapability(Protocol):
    """Deterministic AiiDA operations consumed by the ARIS application."""

    @property
    def bridge_url(self) -> str: ...

    async def get_status(self) -> BridgeSnapshot: ...

    async def get_plugins(self) -> list[str]: ...

    async def get_resources(self) -> dict[str, Any]: ...

    async def get_profiles(self) -> dict[str, Any]: ...

    async def switch_profile(self, profile: str) -> dict[str, Any]: ...


class HttpAiiDACapability:
    """Current adapter backed by the aiida-worker HTTP client."""

    def __init__(self, client: AiiDAWorkerClient) -> None:
        self._client = client

    @property
    def bridge_url(self) -> str:
        return self._client.bridge_url

    async def get_status(self) -> BridgeSnapshot:
        return await self._client.get_status()

    async def get_plugins(self) -> list[str]:
        return await self._client.get_plugins()

    async def get_resources(self) -> dict[str, Any]:
        return await self._client.get_resources()

    async def get_profiles(self) -> dict[str, Any]:
        return await self._client.get_profiles()

    async def switch_profile(self, profile: str) -> dict[str, Any]:
        return await self._client.switch_profile(profile)


aiida_capability: AiiDACapability = HttpAiiDACapability(aiida_worker_client)


__all__ = ["AiiDACapability", "HttpAiiDACapability", "aiida_capability"]
