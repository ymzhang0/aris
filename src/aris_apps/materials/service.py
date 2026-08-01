from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from src.aris_apps.materials.providers.base import MaterialsProvider
from src.aris_apps.materials.schemas import (
    MaterialsProviderInfo,
    StructureArtifact,
    StructureCandidate,
    StructureSearchError,
    StructureSearchRequest,
    StructureSearchResponse,
)


class MaterialsService:
    """Canonical provider-neutral materials structure service."""

    def __init__(
        self,
        providers: list[MaterialsProvider],
        *,
        cache_ttl_seconds: float = 300.0,
    ) -> None:
        self._providers = {provider.info.id: provider for provider in providers}
        self._cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_lock = asyncio.Lock()

    def list_providers(self) -> list[MaterialsProviderInfo]:
        return [self._providers[name].info for name in sorted(self._providers)]

    def _provider(self, provider_id: str) -> MaterialsProvider:
        normalized = str(provider_id or "").strip()
        try:
            return self._providers[normalized]
        except KeyError as exc:
            available = ", ".join(sorted(self._providers))
            raise ValueError(
                f"Unknown materials provider '{normalized}'. Available: {available}"
            ) from exc

    async def _cached(self, key: str, loader) -> Any:
        now = time.monotonic()
        async with self._cache_lock:
            cached = self._cache.get(key)
            if cached is not None and now - cached[0] <= self._cache_ttl_seconds:
                return cached[1]
        value = await loader()
        async with self._cache_lock:
            self._cache[key] = (time.monotonic(), value)
        return value

    async def search(self, request: StructureSearchRequest) -> StructureSearchResponse:
        provider_ids = [request.provider] if request.provider else sorted(self._providers)

        async def query_provider(provider_id: str):
            try:
                provider = self._provider(provider_id)
                provider_request = request.model_copy(update={"provider": provider_id})
                items = await provider.search(provider_request)
                return provider_id, items, None
            except Exception as exc:  # noqa: BLE001
                return provider_id, [], str(exc)

        results = await asyncio.gather(
            *(query_provider(provider_id) for provider_id in provider_ids if provider_id)
        )
        candidates: list[StructureCandidate] = []
        errors: list[StructureSearchError] = []
        seen: set[tuple[str, str, str]] = set()
        for provider_id, items, error in results:
            if error:
                errors.append(
                    StructureSearchError(
                        provider=provider_id,
                        database=request.database,
                        error=error,
                    )
                )
                continue
            for candidate in items:
                identity = (candidate.provider, candidate.database, candidate.entry_id)
                if identity in seen:
                    continue
                seen.add(identity)
                candidates.append(candidate)

        candidates.sort(
            key=lambda item: (
                item.energy_above_hull is None,
                item.energy_above_hull if item.energy_above_hull is not None else float("inf"),
                item.provider,
                item.database,
                item.entry_id,
            )
        )
        return StructureSearchResponse(
            query=request,
            candidates=candidates[: request.limit],
            errors=errors,
        )

    async def get_structure(
        self,
        provider_id: str,
        database: str,
        entry_id: str,
    ) -> StructureArtifact:
        provider = self._provider(provider_id)
        cache_key = json.dumps(
            [provider_id, database, entry_id],
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return await self._cached(
            cache_key,
            lambda: provider.get_structure(database, entry_id),
        )


__all__ = ["MaterialsService"]
