"""Application service for Project domain."""

import os
from pathlib import Path
from typing import List, Optional

from src.aris_apps.projects.config_store import ConfigStore
from src.aris_apps.projects.repository import ProjectRepository
from src.aris_apps.projects.models import Project, ProjectConfig
from src.aris_apps.projects.aiida_gateway import ensure_project_group, relink_project_group


class ProjectError(Exception):
    pass


class ProjectService:
    def __init__(self, config_store: ConfigStore, repository: ProjectRepository):
        self.config_store = config_store
        self.repository = repository

    async def create_project(
        self, folder_path: str, name: str, aiida_enabled: bool, aiida_profile: str
    ) -> Project:
        """Create a new project in the given folder."""
        path = Path(folder_path).resolve()
        if not path.is_dir():
            raise ProjectError(f"Directory does not exist: {path}")

        # Check if project already exists
        existing_config = self.config_store.read_project_config(path)
        if existing_config:
            raise ProjectError(f"Project already initialized at {path}")

        # Ensure group first if AiiDA enabled (almost transactional)
        group_uuid = None
        group_label = None
        if aiida_enabled:
            # We don't have the config yet, so we generate a pre-id
            config = self.config_store.create_project_config(
                path, name, aiida_enabled, aiida_profile
            )
            try:
                group_uuid, group_label = await ensure_project_group(
                    config.project_id, config.name, profile=aiida_profile
                )
                config.aiida.group_uuid = group_uuid
                config.aiida.group_label = group_label
                self.config_store.write_project_config(path, config)
            except Exception as e:
                # Rollback or at least we leave it disconnected
                config.aiida.status = "needs_attention"
                self.config_store.write_project_config(path, config)
                self.repository.upsert_index(config.project_id, str(path))
                raise ProjectError(f"Project created but AiiDA group failed: {e}")
        else:
            config = self.config_store.create_project_config(path, name)

        self.repository.upsert_index(config.project_id, str(path))
        
        project = self.repository.get_by_id(config.project_id)
        if not project:
            raise ProjectError("Failed to read project after creation")
        return project

    async def load_project(self, folder_path: str) -> Project:
        """Load an existing project from a folder and index it."""
        path = Path(folder_path).resolve()
        config = self.config_store.read_project_config(path)
        
        if not config:
            raise ProjectError(f"No .aris/project.json found in {path}")

        if not config.aiida.enabled:
            config.aiida.enabled = True
        if not config.aiida.group_uuid:
            try:
                group_uuid, group_label = await ensure_project_group(
                    config.project_id,
                    config.name,
                    profile=config.aiida.profile,
                )
                config.aiida.group_uuid = group_uuid
                config.aiida.group_label = group_label
                config.aiida.status = "synced"
                self.config_store.write_project_config(path, config)
            except Exception as e:
                config.aiida.status = "needs_attention"
                self.config_store.write_project_config(path, config)
                raise ProjectError(f"Project loaded but AiiDA group failed: {e}") from e
            
        self.repository.upsert_index(config.project_id, str(path))
        
        project = self.repository.get_by_id(config.project_id)
        if not project:
            raise ProjectError("Failed to read project after loading")
        return project
        
    def list_projects(self) -> List[Project]:
        return self.repository.list_all()

    def get_project(self, project_id: str) -> Optional[Project]:
        return self.repository.get_by_id(project_id)

    def rename_project(self, project_id: str, new_name: str) -> Project:
        project = self.get_project(project_id)
        if not project:
            raise ProjectError("Project not found")
            
        path = Path(project.canonical_path)
        config = self.config_store.read_project_config(path)
        if not config:
            raise ProjectError("Project config missing")
            
        config.name = new_name
        # Note: We don't change the group_label automatically to avoid DB drift unless explicit
        self.config_store.write_project_config(path, config)
        
        updated = self.get_project(project_id)
        assert updated is not None
        return updated
        
    async def relink_aiida_group(self, project_id: str, group_uuid: str) -> Project:
        project = self.get_project(project_id)
        if not project:
            raise ProjectError("Project not found")
            
        path = Path(project.canonical_path)
        config = self.config_store.read_project_config(path)
        if not config:
            raise ProjectError("Project config missing")
            
        if not config.aiida.enabled:
            raise ProjectError("AiiDA is not enabled for this project")
            
        try:
            new_group_uuid, new_group_label = await relink_project_group(
                config.project_id, group_uuid
            )
            config.aiida.group_uuid = new_group_uuid
            config.aiida.group_label = new_group_label
            config.aiida.status = "synced"
            self.config_store.write_project_config(path, config)
        except Exception as e:
            raise ProjectError(f"Failed to relink AiiDA group: {e}")
            
        updated = self.get_project(project_id)
        assert updated is not None
        return updated
        
    def remove_from_aris(self, project_id: str) -> None:
        """Remove from global index, do not delete files or AiiDA groups."""
        self.repository.remove_from_index(project_id)
