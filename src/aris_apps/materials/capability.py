from __future__ import annotations

from typing import Protocol

from src.aris_apps.materials.providers import OptimadeProvider
from src.aris_apps.materials.schemas import (
    MaterialsProviderInfo,
    StructureArtifact,
    StructureSearchRequest,
    StructureSearchResponse,
)
from src.aris_apps.materials.service import MaterialsService


class MaterialsCapability(Protocol):
    async def list_providers(self) -> list[MaterialsProviderInfo]: ...

    async def search(self, request: StructureSearchRequest) -> StructureSearchResponse: ...

    async def get_structure(
        self,
        provider: str,
        database: str,
        entry_id: str,
    ) -> StructureArtifact: ...


class ManagedMaterialsCapability:
    def __init__(self, service: MaterialsService) -> None:
        self._service = service

    async def list_providers(self) -> list[MaterialsProviderInfo]:
        return self._service.list_providers()

    async def search(self, request: StructureSearchRequest) -> StructureSearchResponse:
        return await self._service.search(request)

    async def get_structure(
        self,
        provider: str,
        database: str,
        entry_id: str,
    ) -> StructureArtifact:
        return await self._service.get_structure(provider, database, entry_id)


def build_default_materials_capability() -> ManagedMaterialsCapability:
    providers = [
        OptimadeProvider(
            provider_id="materials_project",
            name="Materials Project",
            description="Computed inorganic materials structures exposed through OPTIMADE.",
            databases={"mp": "https://optimade.materialsproject.org/v1"},
            provider_fields=("_mp_stability", "_mp_chemical_system"),
            citations=("https://materialsproject.org/about/cite",),
        ),
        OptimadeProvider(
            provider_id="materials_cloud",
            name="Materials Cloud",
            description="Open research structures from curated Materials Cloud databases.",
            databases={
                "mc3d-pbe-v1": "https://optimade.materialscloud.org/main/mc3d-pbe-v1/v1",
                "mc3d-pbesol-v1": "https://optimade.materialscloud.org/main/mc3d-pbesol-v1/v1",
                "mc3d-pbesol-v2": "https://optimade.materialscloud.org/main/mc3d-pbesol-v2/v1",
                "mc2d": "https://optimade.materialscloud.org/main/mc2d/v1",
                "2dtopo": "https://optimade.materialscloud.org/main/2dtopo/v1",
                "pyrene-mofs": "https://optimade.materialscloud.org/main/pyrene-mofs/v1",
                "curated-cofs": "https://optimade.materialscloud.org/main/curated-cofs/v1",
                "stoceriaitf": "https://optimade.materialscloud.org/main/stoceriaitf/v1",
                "autowannier": "https://optimade.materialscloud.org/main/autowannier/v1",
                "tin-antimony-sulfoiodide": (
                    "https://optimade.materialscloud.org/main/tin-antimony-sulfoiodide/v1"
                ),
            },
            default_databases=("mc3d-pbe-v1",),
            citations=("https://www.materialscloud.org/",),
        ),
    ]
    return ManagedMaterialsCapability(MaterialsService(providers))


materials_capability = build_default_materials_capability()


__all__ = [
    "ManagedMaterialsCapability",
    "MaterialsCapability",
    "build_default_materials_capability",
    "materials_capability",
]
