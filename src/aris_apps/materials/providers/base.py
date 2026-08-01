from __future__ import annotations

from typing import Protocol

from src.aris_apps.materials.schemas import (
    MaterialsProviderInfo,
    StructureArtifact,
    StructureCandidate,
    StructureSearchRequest,
)


class MaterialsProvider(Protocol):
    @property
    def info(self) -> MaterialsProviderInfo: ...

    async def search(self, request: StructureSearchRequest) -> list[StructureCandidate]: ...

    async def get_structure(self, database: str, entry_id: str) -> StructureArtifact: ...


__all__ = ["MaterialsProvider"]
