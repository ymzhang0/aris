"""Store and manage physical configuration files for Projects."""

import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from src.aris_apps.projects.models import (
    GlobalProjectIndex,
    ProjectConfig,
)


def atomic_write_json(path: Path, data: dict) -> None:
    """Safely write JSON to a file by writing to a temp file and replacing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path_str = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    temp_path = Path(temp_path_str)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        # fsync directory would be safer but replace is generally atomic on POSIX
        temp_path.replace(path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


class ConfigStore:
    """Manages reading and writing ARIS project configuration files."""

    def __init__(self, global_index_path: Path):
        self.global_index_path = global_index_path

    def read_global_index(self) -> GlobalProjectIndex:
        if not self.global_index_path.exists():
            return GlobalProjectIndex()
        try:
            with open(self.global_index_path, "r") as f:
                data = json.load(f)
            return GlobalProjectIndex.model_validate(data)
        except Exception:
            # Simple recovery: return an empty index if corrupt
            return GlobalProjectIndex()

    def write_global_index(self, index: GlobalProjectIndex) -> None:
        atomic_write_json(self.global_index_path, index.model_dump())

    def read_project_config(self, project_dir: Path) -> Optional[ProjectConfig]:
        config_path = project_dir / ".aris" / "project.json"
        if not config_path.exists():
            return None
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
            return ProjectConfig.model_validate(data)
        except Exception as e:
            raise RuntimeError(f"Failed to read project config at {config_path}: {e}")

    def write_project_config(self, project_dir: Path, config: ProjectConfig) -> None:
        config_path = project_dir / ".aris" / "project.json"
        atomic_write_json(config_path, config.model_dump())

    def create_project_config(self, project_dir: Path, name: str, aiida_enabled: bool = False, aiida_profile: str = "default") -> ProjectConfig:
        config = ProjectConfig(
            project_id=str(uuid.uuid4()),
            name=name,
        )
        if aiida_enabled:
            config.aiida.enabled = True
            config.aiida.profile = aiida_profile
            # Group will be created and linked later in service/aiida_gateway
            config.aiida.group_label = f"aris.project.{config.project_id}"

        self.write_project_config(project_dir, config)
        return config
