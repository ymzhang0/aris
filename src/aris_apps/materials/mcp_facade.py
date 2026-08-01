from __future__ import annotations

import json
from typing import Any, Protocol

from fastmcp import FastMCP

from src.aris_apps.materials.capability import MaterialsCapability, materials_capability
from src.aris_apps.materials.schemas import (
    StructureImportRequest,
    StructureLookupRequest,
    StructureSearchRequest,
)

_READ_ONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
_IMPORT_ANNOTATIONS = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}


class StructureImporter(Protocol):
    async def import_structure(
        self,
        artifact: dict[str, Any],
        *,
        label: str | None = None,
        description: str | None = None,
        deduplicate: bool = True,
    ) -> dict[str, Any]: ...


class MaterialsMCPFacade:
    def __init__(
        self,
        capability: MaterialsCapability,
        importer: StructureImporter | None = None,
    ) -> None:
        self._capability = capability
        self._importer = importer

    async def providers(self) -> dict[str, Any]:
        providers = await self._capability.list_providers()
        return {"providers": [item.model_dump(mode="json") for item in providers]}

    async def search(self, request: StructureSearchRequest) -> dict[str, Any]:
        response = await self._capability.search(request)
        return response.model_dump(mode="json")

    async def prepare_import(self, request: StructureLookupRequest) -> dict[str, Any]:
        artifact = await self._capability.get_structure(
            request.provider,
            request.database,
            request.entry_id,
        )
        return artifact.model_dump(mode="json")

    async def import_structure(self, request: StructureImportRequest) -> dict[str, Any]:
        if self._importer is None:
            raise RuntimeError("No AiiDA structure importer is configured")
        artifact = await self._capability.get_structure(
            request.provider,
            request.database,
            request.entry_id,
        )
        return await self._importer.import_structure(
            artifact.model_dump(mode="json"),
            label=request.label,
            description=request.description,
            deduplicate=request.deduplicate,
        )


def build_materials_mcp_server(
    capability: MaterialsCapability = materials_capability,
    importer: StructureImporter | None = None,
) -> FastMCP:
    facade = MaterialsMCPFacade(capability, importer)
    server = FastMCP(
        "aris-materials",
        instructions=(
            "Search remote materials databases using explicit structured filters. "
            "Inspect candidates before importing when multiple polymorphs are returned. "
            "Structure import creates an AiiDA data node but never submits a calculation."
        ),
    )

    @server.tool(
        name="materials_list_providers",
        description="List configured remote materials structure providers and databases.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def materials_list_providers() -> dict[str, Any]:
        return await facade.providers()

    @server.tool(
        name="materials_search_structures",
        description="Search remote structure databases with explicit formula, element, or entry-ID filters.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def materials_search_structures(
        request: StructureSearchRequest,
    ) -> dict[str, Any]:
        return await facade.search(request)

    @server.tool(
        name="materials_prepare_import",
        description="Fetch one selected structure and return its normalized import payload without storing it.",
        annotations=_READ_ONLY_ANNOTATIONS,
    )
    async def materials_prepare_import(
        request: StructureLookupRequest,
    ) -> dict[str, Any]:
        return await facade.prepare_import(request)

    if importer is not None:
        @server.tool(
            name="materials_import_structure",
            description="Fetch one selected remote structure and idempotently store it as AiiDA StructureData.",
            annotations=_IMPORT_ANNOTATIONS,
        )
        async def materials_import_structure(
            request: StructureImportRequest,
        ) -> dict[str, Any]:
            return await facade.import_structure(request)

    @server.resource(
        "materials://providers",
        name="Materials providers",
        description="Configured materials databases available to ARIS.",
        mime_type="application/json",
    )
    async def materials_providers_resource() -> str:
        return json.dumps(await facade.providers(), ensure_ascii=False, sort_keys=True)

    return server


__all__ = ["MaterialsMCPFacade", "StructureImporter", "build_materials_mcp_server"]
