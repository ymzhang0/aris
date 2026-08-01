from __future__ import annotations

from typing import Never

import httpx
from fastapi import APIRouter, HTTPException, Request

from src.aris_apps.materials.capability import MaterialsCapability, materials_capability
from src.aris_apps.materials.schemas import (
    StructureArtifact,
    StructureImportReceipt,
    StructureImportRequest,
    StructureLookupRequest,
    StructureSearchRequest,
    StructureSearchResponse,
)

router = APIRouter()


def get_materials_capability(request: Request) -> MaterialsCapability:  # noqa: ARG001
    return materials_capability


def _raise_materials_error(exc: Exception) -> Never:
    if isinstance(exc, httpx.HTTPStatusError):
        status = 404 if exc.response.status_code == 404 else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/providers")
async def list_materials_providers(request: Request):
    capability = get_materials_capability(request)
    return await capability.list_providers()


@router.post("/search", response_model=StructureSearchResponse)
async def search_material_structures(
    payload: StructureSearchRequest,
    request: Request,
) -> StructureSearchResponse:
    capability = get_materials_capability(request)
    return await capability.search(payload)


@router.post("/structure", response_model=StructureArtifact)
async def get_material_structure(
    payload: StructureLookupRequest,
    request: Request,
) -> StructureArtifact:
    capability = get_materials_capability(request)
    try:
        return await capability.get_structure(
            payload.provider,
            payload.database,
            payload.entry_id,
        )
    except Exception as exc:  # noqa: BLE001
        _raise_materials_error(exc)


@router.post("/import", response_model=StructureImportReceipt)
async def import_material_structure(
    payload: StructureImportRequest,
    request: Request,
) -> StructureImportReceipt:
    capability = get_materials_capability(request)
    try:
        artifact = await capability.get_structure(
            payload.provider,
            payload.database,
            payload.entry_id,
        )
        from src.aris_apps.aiida.capabilities import aiida_capability
        from src.aris_core.capabilities import capability_registry

        structure_importer = capability_registry.get("aiida", aiida_capability)
        result = await structure_importer.import_structure(
            artifact.model_dump(mode="json"),
            label=payload.label,
            description=payload.description,
            deduplicate=payload.deduplicate,
        )
        return StructureImportReceipt.model_validate(result)
    except Exception as exc:  # noqa: BLE001
        _raise_materials_error(exc)
