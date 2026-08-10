"""Project-aware context for standalone AiiDA MCP clients."""

from __future__ import annotations

import os
import sys
import asyncio
from pathlib import Path
from typing import Any

from src.aris_core.config import settings
from src.aris_core.memory import JSONMemory
from src.aris_apps.aiida.project_packages import ensure_project_runtime


class AiiDAProjectCatalog:
    """Read ARIS projects and resolve their isolated worker contexts."""

    def __init__(self) -> None:
        self._selected_project_id: str | None = None
        self._last_catalog_active_project_id: str | None = None
        self._runtime_ready: set[str] = set()
        self._runtime_lock = asyncio.Lock()

    def list_projects(self) -> list[dict[str, Any]]:
        memory = JSONMemory(
            namespace="aris_v2_global",
            storage_path=settings.ARIS_MEMORY_DIR,
        )
        raw_store = memory.get_kv("frontend_chat_sessions_v2", {})
        if not isinstance(raw_store, dict):
            raw_store = {}
        raw_projects = raw_store.get("projects", [])
        projects = raw_projects if isinstance(raw_projects, list) else []
        active_project_id = str(raw_store.get("active_project_id") or "").strip()
        session_counts: dict[str, int] = {}
        for session in raw_store.get("sessions", []) if isinstance(raw_store.get("sessions"), list) else []:
            if isinstance(session, dict):
                project_id = str(session.get("project_id") or "").strip()
                if project_id:
                    session_counts[project_id] = session_counts.get(project_id, 0) + 1
        normalized_projects = [
            {
                "id": str(project.get("id") or ""),
                "name": str(project.get("name") or "Project"),
                "root_path": str(project.get("root_path") or ""),
                "python_interpreter_path": str(project.get("python_interpreter_path") or project.get("python_env") or "") or None,
                "aiida_profile": str(project.get("aiida_profile") or "") or None,
                "active": str(project.get("id") or "") == active_project_id,
                "session_count": session_counts.get(str(project.get("id") or ""), 0),
            }
            for project in projects
            if isinstance(project, dict) and str(project.get("id") or "").strip()
        ]
        project_ids = {str(item.get("id") or "") for item in normalized_projects}
        if active_project_id != self._last_catalog_active_project_id:
            self._selected_project_id = active_project_id or None
            self._last_catalog_active_project_id = active_project_id
        if self._selected_project_id not in project_ids:
            self._selected_project_id = next(
                (str(item.get("id")) for item in normalized_projects if item.get("active")),
                str(normalized_projects[0].get("id")) if normalized_projects else None,
            )
        return [
            {**project, "active": str(project.get("id") or "") == self._selected_project_id}
            for project in normalized_projects
        ]

    def select_project(self, project_id: str) -> dict[str, Any]:
        cleaned = str(project_id or "").strip()
        project = next(
            (item for item in self.list_projects() if str(item.get("id") or "") == cleaned),
            None,
        )
        if project is None:
            raise ValueError(f"Unknown ARIS project: {cleaned or '<empty>'}")
        self._selected_project_id = cleaned
        return {**project, "active": True}

    async def ensure_runtime(self, project_id: str | None = None) -> dict[str, Any]:
        """Ensure the selected project's AiiDA interpreter is ready for MCP."""

        projects = self.list_projects()
        target_id = str(project_id or self._selected_project_id or "").strip()
        project = next(
            (item for item in projects if str(item.get("id") or "") == target_id),
            None,
        )
        if project is None:
            raise ValueError(
                "Select an ARIS project first with aiida_select_project, or provide project_id."
            )

        async with self._runtime_lock:
            if target_id not in self._runtime_ready:
                inspection = await ensure_project_runtime(project)
                self._persist_runtime_interpreter(target_id, inspection)
                self._runtime_ready.add(target_id)
            else:
                inspection = await ensure_project_runtime(project)
        return inspection

    def _persist_runtime_interpreter(self, project_id: str, inspection: dict[str, Any]) -> None:
        interpreter = str(inspection.get("python_interpreter_path") or "").strip()
        if not interpreter:
            return
        memory = JSONMemory(
            namespace="aris_v2_global",
            storage_path=settings.ARIS_MEMORY_DIR,
        )
        raw_store = memory.get_kv("frontend_chat_sessions_v2", {})
        if not isinstance(raw_store, dict):
            return
        projects = raw_store.get("projects")
        if not isinstance(projects, list):
            return
        changed = False
        for project in projects:
            if isinstance(project, dict) and str(project.get("id") or "") == project_id:
                if project.get("python_interpreter_path") != interpreter:
                    project["python_interpreter_path"] = interpreter
                    changed = True
                break
        if changed:
            memory.set_kv("frontend_chat_sessions_v2", raw_store)

    def selected_project_id(self) -> str | None:
        return self._selected_project_id

    def context_for(self, project_id: str | None = None) -> dict[str, str]:
        projects = self.list_projects()
        target_id = str(project_id or self._selected_project_id or "").strip()
        project = next(
            (item for item in projects if str(item.get("id") or "") == target_id),
            None,
        )
        if project is None:
            raise ValueError(
                "Select an ARIS project first with aiida_select_project, or provide project_id."
            )

        workspace = Path(str(project.get("root_path") or "")).expanduser().resolve()
        configured_python = str(project.get("python_interpreter_path") or "").strip()
        candidates = [
            Path(configured_python).expanduser() if configured_python else None,
            workspace / ".venv" / "bin" / "python",
            workspace / ".venv" / "Scripts" / "python.exe",
            Path(sys.executable),
        ]
        interpreter = next(
            (candidate.resolve() for candidate in candidates if candidate and candidate.is_file()),
            Path(sys.executable).resolve(),
        )
        profile = (
            str(project.get("aiida_profile") or "").strip()
            or os.environ.get("ARIS_MCP_PROFILE", "").strip()
            or os.environ.get("AIIDA_PROFILE", "").strip()
            or "dev"
        )
        self._selected_project_id = target_id
        return {
            "project_id": target_id,
            "workspace_path": str(workspace),
            "python_interpreter_path": str(interpreter),
            "profile_name": profile,
        }


__all__ = ["AiiDAProjectCatalog"]
