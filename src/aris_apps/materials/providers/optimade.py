from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from src.aris_apps.materials.schemas import (
    MaterialsProviderInfo,
    SpeciesComponent,
    StructureArtifact,
    StructureCandidate,
    StructureSearchRequest,
    StructureSite,
    StructureSource,
)


def _escape_filter_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _dimension(attributes: dict[str, Any]) -> int | None:
    raw = attributes.get("dimension_types")
    if isinstance(raw, list) and len(raw) == 3:
        return sum(1 for value in raw if bool(value))
    raw = attributes.get("nperiodic_dimensions")
    return int(raw) if isinstance(raw, int) and 0 <= raw <= 3 else None


def _energy_above_hull(attributes: dict[str, Any]) -> float | None:
    stability = attributes.get("_mp_stability")
    if not isinstance(stability, dict):
        return None
    values: list[float] = []
    for payload in stability.values():
        if not isinstance(payload, dict):
            continue
        value = payload.get("energy_above_hull")
        if isinstance(value, (int, float)):
            values.append(float(value))
    return min(values) if values else None


class OptimadeProvider:
    """OPTIMADE-backed implementation shared by remote structure databases."""

    def __init__(
        self,
        *,
        provider_id: str,
        name: str,
        description: str,
        databases: dict[str, str],
        default_databases: tuple[str, ...] | None = None,
        client: httpx.AsyncClient | None = None,
        provider_fields: tuple[str, ...] = (),
        license_name: str | None = None,
        citations: tuple[str, ...] = (),
    ) -> None:
        self._provider_id = provider_id
        self._name = name
        self._description = description
        self._databases = {
            str(database).strip(): str(base_url).rstrip("/")
            for database, base_url in databases.items()
        }
        self._default_databases = tuple(default_databases or self._databases)
        unknown_defaults = set(self._default_databases) - set(self._databases)
        if unknown_defaults:
            raise ValueError(
                f"Default OPTIMADE databases are not configured: {sorted(unknown_defaults)}"
            )
        self._client = client
        self._provider_fields = tuple(provider_fields)
        self._license_name = license_name
        self._citations = list(citations)

    @property
    def info(self) -> MaterialsProviderInfo:
        return MaterialsProviderInfo(
            id=self._provider_id,
            name=self._name,
            description=self._description,
            databases=sorted(self._databases),
        )

    def _client_or_default(self) -> tuple[httpx.AsyncClient, bool]:
        if self._client is not None:
            return self._client, False
        return httpx.AsyncClient(timeout=httpx.Timeout(15.0)), True

    def _database_url(self, database: str) -> str:
        normalized = str(database or "").strip()
        try:
            return self._databases[normalized]
        except KeyError as exc:
            available = ", ".join(sorted(self._databases))
            raise ValueError(
                f"Unknown {self._provider_id} database '{normalized}'. Available: {available}"
            ) from exc

    def _search_filter(self, request: StructureSearchRequest) -> str:
        clauses: list[str] = []
        if request.entry_id:
            clauses.append(f'id="{_escape_filter_string(request.entry_id)}"')
        if request.formula:
            clauses.append(
                f'chemical_formula_reduced="{_escape_filter_string(request.formula)}"'
            )
        if request.elements:
            values = ", ".join(f'"{symbol}"' for symbol in request.elements)
            clauses.append(f"elements HAS ALL {values}")
            if request.exact_elements:
                clauses.append(f"nelements={len(request.elements)}")
        return " AND ".join(clauses)

    async def search(self, request: StructureSearchRequest) -> list[StructureCandidate]:
        databases = [request.database] if request.database else list(self._default_databases)
        remaining = request.limit
        candidates: list[StructureCandidate] = []
        for database in databases:
            if remaining <= 0:
                break
            assert database is not None
            base_url = self._database_url(database)
            fields = [
                "immutable_id",
                "last_modified",
                "chemical_formula_reduced",
                "elements",
                "nsites",
                "dimension_types",
                "nperiodic_dimensions",
                *self._provider_fields,
            ]
            fetch_limit = 50 if request.max_energy_above_hull is not None else remaining
            params = {
                "filter": self._search_filter(request),
                "page_limit": str(fetch_limit),
                "response_fields": ",".join(fields),
            }
            client, owns_client = self._client_or_default()
            try:
                response = await client.get(f"{base_url}/structures", params=params)
                response.raise_for_status()
                payload = response.json()
            finally:
                if owns_client:
                    await client.aclose()
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list):
                raise ValueError(f"{self._name} returned an invalid OPTIMADE response")
            for entry in data:
                candidate = self._candidate(database, base_url, entry)
                if (
                    request.max_energy_above_hull is not None
                    and candidate.energy_above_hull is not None
                    and candidate.energy_above_hull > request.max_energy_above_hull
                ):
                    continue
                candidates.append(candidate)
                remaining -= 1
                if remaining <= 0:
                    break
        return candidates

    def _candidate(
        self,
        database: str,
        base_url: str,
        entry: Any,
    ) -> StructureCandidate:
        if not isinstance(entry, dict):
            raise ValueError("OPTIMADE structure entry must be an object")
        entry_id = str(entry.get("id") or "").strip()
        attributes = entry.get("attributes")
        if not entry_id or not isinstance(attributes, dict):
            raise ValueError("OPTIMADE structure entry is missing id or attributes")
        provider_fields = {
            key: attributes[key]
            for key in self._provider_fields
            if key in attributes
        }
        return StructureCandidate(
            provider=self._provider_id,
            database=database,
            entry_id=entry_id,
            immutable_id=attributes.get("immutable_id"),
            formula=attributes.get("chemical_formula_reduced"),
            elements=[str(value) for value in attributes.get("elements") or []],
            nsites=attributes.get("nsites"),
            dimensionality=_dimension(attributes),
            energy_above_hull=_energy_above_hull(attributes),
            last_modified=attributes.get("last_modified"),
            source_url=f"{base_url}/structures/{quote(entry_id, safe='')}",
            provider_fields=provider_fields,
        )

    async def get_structure(self, database: str, entry_id: str) -> StructureArtifact:
        base_url = self._database_url(database)
        client, owns_client = self._client_or_default()
        try:
            response = await client.get(
                f"{base_url}/structures/{quote(entry_id, safe='')}",
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            if owns_client:
                await client.aclose()
        entry = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(entry, dict):
            raise ValueError(f"{self._name} returned an invalid OPTIMADE structure")
        return self._artifact(database, base_url, entry, payload.get("meta") or {})

    def _artifact(
        self,
        database: str,
        base_url: str,
        entry: dict[str, Any],
        meta: dict[str, Any],
    ) -> StructureArtifact:
        entry_id = str(entry.get("id") or "").strip()
        attributes = entry.get("attributes")
        if not entry_id or not isinstance(attributes, dict):
            raise ValueError("OPTIMADE structure entry is missing id or attributes")

        lattice = attributes.get("lattice_vectors")
        positions = attributes.get("cartesian_site_positions")
        species_at_sites = attributes.get("species_at_sites")
        species_definitions = attributes.get("species") or []
        if not isinstance(lattice, list) or len(lattice) != 3:
            raise ValueError("OPTIMADE structure is missing a 3x3 lattice")
        if not isinstance(positions, list) or not isinstance(species_at_sites, list):
            raise ValueError("OPTIMADE structure is missing site positions or species")
        if len(positions) != len(species_at_sites) or not positions:
            raise ValueError("OPTIMADE site positions and species must have equal non-zero length")

        species_by_name: dict[str, list[SpeciesComponent]] = {}
        for definition in species_definitions:
            if not isinstance(definition, dict):
                continue
            name = str(definition.get("name") or "").strip()
            symbols = definition.get("chemical_symbols") or []
            concentrations = definition.get("concentration") or []
            if not name or len(symbols) != len(concentrations):
                continue
            species_by_name[name] = [
                SpeciesComponent(symbol=str(symbol), concentration=float(concentration))
                for symbol, concentration in zip(symbols, concentrations, strict=True)
                if str(symbol) != "vacancy" and float(concentration) > 0
            ]

        sites: list[StructureSite] = []
        for position, species_name_raw in zip(positions, species_at_sites, strict=True):
            species_name = str(species_name_raw or "").strip()
            components = species_by_name.get(species_name)
            if not components:
                if species_name == "vacancy":
                    raise ValueError("OPTIMADE structure contains a vacancy-only site")
                components = [SpeciesComponent(symbol=species_name, concentration=1.0)]
            sites.append(
                StructureSite(
                    position=tuple(float(value) for value in position),
                    species=components,
                    name=species_name,
                )
            )

        dimension_types = attributes.get("dimension_types")
        if isinstance(dimension_types, list) and len(dimension_types) == 3:
            pbc = tuple(bool(value) for value in dimension_types)
        else:
            pbc = (True, True, True)
        implementation = meta.get("implementation") if isinstance(meta, dict) else None
        implementation_version = None
        if isinstance(implementation, dict) and implementation.get("version"):
            implementation_version = str(implementation["version"])

        provider_fields = {
            key: attributes[key]
            for key in self._provider_fields
            if key in attributes
        }
        return StructureArtifact(
            formula=attributes.get("chemical_formula_reduced"),
            lattice_vectors=tuple(tuple(float(value) for value in vector) for vector in lattice),
            periodic_boundary_conditions=pbc,
            sites=sites,
            source=StructureSource(
                provider=self._provider_id,
                database=database,
                entry_id=entry_id,
                immutable_id=attributes.get("immutable_id"),
                url=f"{base_url}/structures/{quote(entry_id, safe='')}",
                license=self._license_name,
                citations=self._citations,
                provider_fields={
                    **provider_fields,
                    "last_modified": attributes.get("last_modified"),
                    "optimade_api_version": meta.get("api_version") if isinstance(meta, dict) else None,
                    "optimade_implementation_version": implementation_version,
                },
            ),
        )


__all__ = ["OptimadeProvider"]
