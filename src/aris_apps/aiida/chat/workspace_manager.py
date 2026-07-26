"""Filesystem boundary for ARIS project workspaces."""

from __future__ import annotations

import hashlib
import re
import shutil
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

PROJECT_CODES_DIRNAME = "codes"
PROJECT_DATA_DIRNAME = "data"


class ChatWorkspaceManager:
    """Own project layout, path validation, and safe workspace cleanup."""

    def __init__(self, managed_projects_root_provider: Callable[[], str | Path]) -> None:
        self._managed_projects_root_provider = managed_projects_root_provider

    @staticmethod
    def resolve_filesystem_path(path_value: Any) -> Path | None:
        cleaned = str(path_value or "").strip()
        if not cleaned:
            return None
        return Path(cleaned).expanduser().resolve()

    def managed_projects_root(self) -> Path:
        root = self.resolve_filesystem_path(self._managed_projects_root_provider())
        if root is None:
            root = Path.home() / ".aris" / "projects"
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _managed_project_directory_name(project_id: str) -> str:
        cleaned = str(project_id or "").strip()
        if (
            len(cleaned) <= 128
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", cleaned)
            and cleaned not in {".", ".."}
        ):
            return cleaned
        digest = hashlib.sha256(
            cleaned.encode("utf-8", errors="replace")
        ).hexdigest()[:16]
        return f"project-{digest}"

    def managed_project_root(self, project_id: str) -> Path:
        return self.managed_projects_root() / self._managed_project_directory_name(project_id)

    def project_root_path(self, project: dict[str, Any]) -> Path:
        return self.resolve_filesystem_path(project.get("root_path")) or self.managed_project_root(
            str(project.get("id") or uuid4().hex)
        )

    def project_codes_root_path(self, project: dict[str, Any]) -> Path:
        return self.project_root_path(project) / PROJECT_CODES_DIRNAME

    def project_data_root_path(self, project: dict[str, Any]) -> Path:
        return self.project_root_path(project) / PROJECT_DATA_DIRNAME

    def get_session_slug(self, session: dict[str, Any]) -> str:
        stored = str(session.get("session_slug") or "").strip()
        if stored:
            return stored
        workspace_path = self.resolve_filesystem_path(session.get("workspace_path"))
        if workspace_path is not None:
            workspace_name = workspace_path.name.strip()
            if workspace_name:
                return workspace_name
        session_id = str(session.get("id") or "").strip()
        return session_id or "session"

    @staticmethod
    def is_path_within(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    @staticmethod
    def _safe_rmtree(path: Path | None) -> None:
        if path is None:
            return
        with suppress(FileNotFoundError):
            shutil.rmtree(path, ignore_errors=True)

    def cleanup_project_workspace_dir(self, project: dict[str, Any]) -> None:
        root = self.project_root_path(project)
        managed_root = self.managed_project_root(str(project.get("id") or ""))
        if root == managed_root:
            self._safe_rmtree(root)

    def normalize_project_root_path(self, path_value: Any, *, project_id: str) -> str:
        resolved = self.resolve_filesystem_path(path_value) or self.managed_project_root(project_id)
        if resolved.exists() and not resolved.is_dir():
            resolved = self.managed_project_root(project_id)
        return str(resolved)

    def validate_new_project_root_path(self, path_value: Any, *, project_id: str) -> str:
        resolved = self.resolve_filesystem_path(path_value)
        if resolved is None:
            resolved = self.managed_project_root(project_id)
        if resolved.exists() and not resolved.is_dir():
            raise ValueError(f"Project root path points to a file: {resolved}")
        return str(resolved)

    @staticmethod
    def ensure_directory(path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_project_workspace_dir(self, project: dict[str, Any]) -> Path:
        root = self.ensure_directory(self.project_root_path(project))
        project["root_path"] = str(root)
        self.ensure_directory(root / PROJECT_CODES_DIRNAME)
        self.ensure_directory(root / PROJECT_DATA_DIRNAME)
        return root

    def ensure_session_workspace_dir(
        self,
        project: dict[str, Any],
        session: dict[str, Any],
    ) -> str:
        """Point a session at its shared project root."""
        project_root = self.ensure_project_workspace_dir(project)
        session["project_id"] = str(project["id"])
        session["workspace_path"] = str(project_root)
        return str(project_root)

    def project_uses_managed_root(self, project: dict[str, Any]) -> bool:
        project_id = str(project.get("id") or "").strip()
        if not project_id:
            return False
        root = self.project_root_path(project)
        managed_root = self.managed_project_root(project_id)
        with suppress(OSError, RuntimeError, ValueError):
            return root.resolve() == managed_root.resolve()
        return str(root) == str(managed_root)

    def project_default_environment_mode(self, project: dict[str, Any]) -> str:
        return "worker-default" if self.project_uses_managed_root(project) else "project-auto"

    @staticmethod
    def resolve_workspace_target_path(
        workspace_root: Path,
        relative_path: str | None = None,
    ) -> Path:
        target = workspace_root
        cleaned_relative = str(relative_path or "").strip().strip("/")
        if cleaned_relative:
            resolved_root = workspace_root.resolve()
            target = (workspace_root / cleaned_relative).resolve()
            try:
                target.relative_to(resolved_root)
            except ValueError as exc:
                raise ValueError("Workspace path escapes the session root") from exc
        return target


__all__ = [
    "ChatWorkspaceManager",
    "PROJECT_CODES_DIRNAME",
    "PROJECT_DATA_DIRNAME",
]
