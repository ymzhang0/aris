"""Project domain models for ARIS."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ProjectAiiDAConfig(BaseModel):
    """Configuration for a project's AiiDA integration."""

    enabled: bool = False
    profile: str = "default"
    group_uuid: Optional[str] = None
    group_label: Optional[str] = None
    status: str = "ready"


class ProjectRuntimeConfig(BaseModel):
    """Configuration for a project's execution environment."""

    python_interpreter: Optional[str] = None


class ProjectConfig(BaseModel):
    """Schema for the .aris/project.json file within the project directory."""

    schema_version: int = Field(1, description="Version of the project schema.")
    project_id: str = Field(..., description="Stable UUID of the project.")
    name: str = Field(..., description="Name of the project.")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    aiida: ProjectAiiDAConfig = Field(default_factory=ProjectAiiDAConfig)
    runtime: ProjectRuntimeConfig = Field(default_factory=ProjectRuntimeConfig)


class ProjectIndexItem(BaseModel):
    """An entry in the global ARIS projects index (~/.aris/projects/index.json)."""

    project_id: str
    canonical_path: str
    last_opened_at: datetime
    pinned: bool = False
    order: int = 0


class GlobalProjectIndex(BaseModel):
    """Schema for the global projects index file."""

    schema_version: int = 1
    projects: list[ProjectIndexItem] = Field(default_factory=list)


class Project(BaseModel):
    """The canonical ARIS Project entity combining config and local state."""

    project_id: str
    name: str
    canonical_path: str
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime
    aiida: ProjectAiiDAConfig
    runtime: ProjectRuntimeConfig
    is_legacy_unbound: bool = False
