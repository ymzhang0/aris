"""Repository for managing Project entities."""

import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.aris_apps.projects.config_store import ConfigStore
from src.aris_apps.projects.models import (
    GlobalProjectIndex,
    Project,
    ProjectIndexItem,
)


class ProjectRepository:
    def __init__(self, config_store: ConfigStore):
        self.config_store = config_store

    def _build_project(self, index_item: ProjectIndexItem, is_legacy_unbound: bool = False) -> Optional[Project]:
        if is_legacy_unbound:
            # We construct a synthetic Project for legacy sessions missing directories
            # They don't have a real path or local config.
            return None

        project_dir = Path(index_item.canonical_path)
        if not project_dir.is_dir():
            return None
        
        try:
            config = self.config_store.read_project_config(project_dir)
        except Exception:
            return None

        if not config:
            return None

        return Project(
            project_id=config.project_id,
            name=config.name,
            canonical_path=index_item.canonical_path,
            created_at=config.created_at,
            updated_at=config.updated_at,
            last_opened_at=index_item.last_opened_at,
            aiida=config.aiida,
            runtime=config.runtime,
            is_legacy_unbound=False,
        )

    def list_all(self) -> List[Project]:
        index = self.config_store.read_global_index()
        projects = []
        for item in index.projects:
            proj = self._build_project(item)
            if proj:
                projects.append(proj)
        
        # Sort by last opened
        projects.sort(key=lambda p: p.last_opened_at, reverse=True)
        return projects

    def get_by_id(self, project_id: str) -> Optional[Project]:
        index = self.config_store.read_global_index()
        for item in index.projects:
            if item.project_id == project_id:
                return self._build_project(item)
        return None

    def upsert_index(self, project_id: str, canonical_path: str) -> None:
        index = self.config_store.read_global_index()
        now = datetime.utcnow()
        
        existing = next((i for i in index.projects if i.project_id == project_id or i.canonical_path == canonical_path), None)
        
        if existing:
            # Update
            existing.project_id = project_id # Ensure UUID matches if matched by path
            existing.canonical_path = canonical_path
            existing.last_opened_at = now
        else:
            # Add
            item = ProjectIndexItem(
                project_id=project_id,
                canonical_path=canonical_path,
                last_opened_at=now
            )
            index.projects.append(item)
            
        self.config_store.write_global_index(index)
        
    def remove_from_index(self, project_id: str) -> None:
        index = self.config_store.read_global_index()
        index.projects = [p for p in index.projects if p.project_id != project_id]
        self.config_store.write_global_index(index)
