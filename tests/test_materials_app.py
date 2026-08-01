from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from src.aris_apps.materials.mcp_facade import build_materials_mcp_server
from src.aris_apps.materials.providers.optimade import OptimadeProvider
from src.aris_apps.materials.schemas import (
    MaterialsProviderInfo,
    SpeciesComponent,
    StructureArtifact,
    StructureSearchRequest,
    StructureSearchResponse,
    StructureSite,
    StructureSource,
)
from src.aris_apps.materials.service import MaterialsService
from src.aris_core.plugins import load_app_manifest


def _optimade_entry() -> dict[str, Any]:
    return {
        "type": "structures",
        "id": "mp-149",
        "attributes": {
            "immutable_id": "task-149",
            "last_modified": "2026-01-01T00:00:00Z",
            "chemical_formula_reduced": "Si",
            "elements": ["Si"],
            "nelements": 1,
            "nsites": 2,
            "dimension_types": [1, 1, 1],
            "lattice_vectors": [
                [0.0, 2.715, 2.715],
                [2.715, 0.0, 2.715],
                [2.715, 2.715, 0.0],
            ],
            "cartesian_site_positions": [[0.0, 0.0, 0.0], [1.3575, 1.3575, 1.3575]],
            "species_at_sites": ["Si", "Si"],
            "species": [
                {
                    "name": "Si",
                    "chemical_symbols": ["Si"],
                    "concentration": [1.0],
                }
            ],
            "_mp_stability": {
                "GGA_GGA+U": {"energy_above_hull": 0.0}
            },
        },
    }


@pytest.mark.anyio
async def test_optimade_provider_searches_and_normalizes_structure() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/structures"):
            return httpx.Response(200, json={"data": [_optimade_entry()], "meta": {}})
        return httpx.Response(
            200,
            json={
                "data": _optimade_entry(),
                "meta": {"implementation": {"version": "1.2.3"}},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OptimadeProvider(
        provider_id="materials_project",
        name="Materials Project",
        description="test",
        databases={"mp": "https://example.test/v1"},
        client=client,
        provider_fields=("_mp_stability",),
    )

    search = await provider.search(StructureSearchRequest(formula="Si", limit=5))
    artifact = await provider.get_structure("mp", "mp-149")
    await client.aclose()

    assert len(search) == 1
    assert search[0].entry_id == "mp-149"
    assert search[0].energy_above_hull == 0.0
    assert search[0].dimensionality == 3
    assert artifact.formula == "Si"
    assert artifact.source.source_key == "materials_project:mp:mp-149:task-149"
    assert len(artifact.sites) == 2
    assert requests[0].url.params["filter"] == 'chemical_formula_reduced="Si"'


class _FailingProvider:
    info = MaterialsProviderInfo(
        id="broken",
        name="Broken",
        databases=["default"],
    )

    async def search(self, request):  # noqa: ARG002
        raise RuntimeError("provider unavailable")

    async def get_structure(self, database, entry_id):  # noqa: ARG002
        raise RuntimeError("provider unavailable")


class _WorkingProvider:
    info = MaterialsProviderInfo(
        id="working",
        name="Working",
        databases=["default"],
    )

    async def search(self, request):
        from src.aris_apps.materials.schemas import StructureCandidate

        return [
            StructureCandidate(
                provider="working",
                database="default",
                entry_id="si-1",
                formula=request.formula,
                elements=["Si"],
                source_url="https://example.test/si-1",
            )
        ]

    async def get_structure(self, database, entry_id):
        return _artifact(provider="working", database=database, entry_id=entry_id)


@pytest.mark.anyio
async def test_materials_service_preserves_partial_provider_failures() -> None:
    service = MaterialsService([_FailingProvider(), _WorkingProvider()])

    response = await service.search(StructureSearchRequest(formula="Si"))

    assert [item.entry_id for item in response.candidates] == ["si-1"]
    assert response.errors[0].provider == "broken"
    assert response.errors[0].error == "provider unavailable"


def _artifact(
    *,
    provider: str = "materials_project",
    database: str = "mp",
    entry_id: str = "mp-149",
) -> StructureArtifact:
    return StructureArtifact(
        formula="Si",
        lattice_vectors=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        sites=[
            StructureSite(
                position=(0.0, 0.0, 0.0),
                species=[SpeciesComponent(symbol="Si", concentration=1.0)],
                name="Si",
            )
        ],
        source=StructureSource(
            provider=provider,
            database=database,
            entry_id=entry_id,
            immutable_id="immutable-1",
            url="https://example.test/structure",
        ),
    )


class _MaterialsCapability:
    async def list_providers(self):
        return [MaterialsProviderInfo(id="materials_project", name="Materials Project", databases=["mp"])]

    async def search(self, request):
        return StructureSearchResponse(query=request, candidates=[])

    async def get_structure(self, provider, database, entry_id):
        return _artifact(provider=provider, database=database, entry_id=entry_id)


class _Importer:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def import_structure(self, artifact, **kwargs):
        self.calls.append({"artifact": artifact, **kwargs})
        return {
            "status": "success",
            "pk": 42,
            "uuid": "uuid-42",
            "formula": "Si",
            "source_key": "materials_project:mp:mp-149:immutable-1",
            "deduplicated": False,
        }


@pytest.mark.anyio
async def test_materials_mcp_exposes_search_prepare_and_idempotent_import() -> None:
    importer = _Importer()
    server = build_materials_mcp_server(_MaterialsCapability(), importer)
    tools = {tool.name: tool for tool in await server.list_tools()}

    assert set(tools) == {
        "materials_list_providers",
        "materials_search_structures",
        "materials_prepare_import",
        "materials_import_structure",
    }
    assert tools["materials_search_structures"].annotations.readOnlyHint is True
    assert tools["materials_import_structure"].annotations.readOnlyHint is False
    assert tools["materials_import_structure"].annotations.destructiveHint is False

    result = await server.call_tool(
        "materials_import_structure",
        {
            "request": {
                "provider": "materials_project",
                "database": "mp",
                "entry_id": "mp-149",
            }
        },
    )

    assert result.structured_content["pk"] == 42
    assert importer.calls[0]["deduplicate"] is True


def test_materials_manifest_is_a_peer_aris_app() -> None:
    manifest = load_app_manifest("materials")
    app = FastAPI()
    manifest.include_routes(app)

    assert manifest.name == "materials"
    assert manifest.api_prefix == "/api/materials"
    assert not hasattr(manifest, "agent_module")
    paths = {route.path for route in app.routes}
    assert "/api/materials/providers" in paths
    assert "/api/materials/search" in paths
    assert "/api/materials/structure" in paths
    assert "/api/materials/import" in paths
