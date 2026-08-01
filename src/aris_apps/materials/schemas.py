from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ELEMENT_PATTERN = re.compile(r"^[A-Z][a-z]?$|^X$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,254}$")


class MaterialsProviderInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    databases: list[str] = Field(default_factory=list)
    supports_api_key: bool = False


class StructureSearchRequest(BaseModel):
    """Explicit structure search protocol shared by HTTP, MCP, and the agent."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    database: str | None = None
    entry_id: str | None = None
    formula: str | None = None
    elements: list[str] = Field(default_factory=list)
    exact_elements: bool = True
    max_energy_above_hull: float | None = Field(default=None, ge=0)
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("provider", "database", "entry_id", "formula")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        cleaned = str(value or "").strip()
        return cleaned or None

    @field_validator("provider", "database", "entry_id")
    @classmethod
    def validate_identifier(cls, value: str | None) -> str | None:
        if value is not None and not _IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError("Identifier contains unsupported characters")
        return value

    @field_validator("elements")
    @classmethod
    def validate_elements(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            symbol = str(value or "").strip()
            if not _ELEMENT_PATTERN.fullmatch(symbol):
                raise ValueError(f"Invalid chemical element symbol: {symbol or value!r}")
            if symbol not in normalized:
                normalized.append(symbol)
        return normalized

    @model_validator(mode="after")
    def validate_query(self) -> "StructureSearchRequest":
        if not self.entry_id and not self.formula and not self.elements:
            raise ValueError("At least one of entry_id, formula, or elements is required")
        return self


class StructureCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    database: str
    entry_id: str
    immutable_id: str | None = None
    formula: str | None = None
    elements: list[str] = Field(default_factory=list)
    nsites: int | None = Field(default=None, ge=0)
    dimensionality: int | None = Field(default=None, ge=0, le=3)
    energy_above_hull: float | None = None
    last_modified: str | None = None
    source_url: str
    provider_fields: dict[str, Any] = Field(default_factory=dict)


class StructureSearchError(BaseModel):
    provider: str
    database: str | None = None
    error: str


class StructureSearchResponse(BaseModel):
    query: StructureSearchRequest
    candidates: list[StructureCandidate] = Field(default_factory=list)
    errors: list[StructureSearchError] = Field(default_factory=list)


class SpeciesComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    concentration: float = Field(gt=0, le=1)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        symbol = str(value or "").strip()
        if not _ELEMENT_PATTERN.fullmatch(symbol):
            raise ValueError(f"Invalid chemical element symbol: {symbol!r}")
        return symbol


class StructureSite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: tuple[float, float, float]
    species: list[SpeciesComponent] = Field(min_length=1)
    name: str | None = None

    @field_validator("position")
    @classmethod
    def validate_position(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        if not all(math.isfinite(component) for component in value):
            raise ValueError("Site positions must be finite")
        return value

    @model_validator(mode="after")
    def validate_concentrations(self) -> "StructureSite":
        total = sum(item.concentration for item in self.species)
        if total > 1.0 + 1e-6:
            raise ValueError("Species concentrations at each site cannot exceed one")
        return self


class StructureSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    database: str
    entry_id: str
    immutable_id: str | None = None
    url: str
    retrieved_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    database_version: str | None = None
    license: str | None = None
    citations: list[str] = Field(default_factory=list)
    provider_fields: dict[str, Any] = Field(default_factory=dict)

    @property
    def source_key(self) -> str:
        version = (
            self.immutable_id
            or self.database_version
            or self.provider_fields.get("last_modified")
            or "current"
        )
        return f"{self.provider}:{self.database}:{self.entry_id}:{version}"


class StructureArtifact(BaseModel):
    """Transport-neutral structure payload suitable for an AiiDA StructureData."""

    model_config = ConfigDict(extra="forbid")

    formula: str | None = None
    lattice_vectors: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]
    periodic_boundary_conditions: tuple[bool, bool, bool] = (True, True, True)
    sites: list[StructureSite] = Field(min_length=1)
    source: StructureSource

    @field_validator("lattice_vectors")
    @classmethod
    def validate_lattice(
        cls,
        value: tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
        ],
    ):
        if not all(math.isfinite(component) for vector in value for component in vector):
            raise ValueError("Lattice vectors must be finite")
        return value


class StructureLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    database: str
    entry_id: str

    @field_validator("provider", "database", "entry_id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not _IDENTIFIER_PATTERN.fullmatch(cleaned):
            raise ValueError("Identifier contains unsupported characters")
        return cleaned


class StructureImportRequest(StructureLookupRequest):
    label: str | None = None
    description: str | None = None
    deduplicate: bool = True


class StructureImportReceipt(BaseModel):
    status: str
    pk: int = Field(gt=0)
    uuid: str
    formula: str | None = None
    source_key: str
    deduplicated: bool = False


__all__ = [
    "MaterialsProviderInfo",
    "SpeciesComponent",
    "StructureArtifact",
    "StructureCandidate",
    "StructureImportReceipt",
    "StructureImportRequest",
    "StructureLookupRequest",
    "StructureSearchError",
    "StructureSearchRequest",
    "StructureSearchResponse",
    "StructureSite",
    "StructureSource",
]
