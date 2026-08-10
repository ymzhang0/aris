"""Project-scoped Python environment and package management."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement

from src.aris_core.runtime import ProjectWorkerProcessManager, get_worker_process_manager


BASE_RUNTIME_REQUIREMENTS = ("aiida-core>=2.7.3", "pydantic>=2.10")
_PACKAGE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ProjectPackageError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail


def _validated_interpreter(python_interpreter_path: str | None) -> Path:
    cleaned = str(python_interpreter_path or "").strip()
    if not cleaned:
        raise ProjectPackageError("Project Python interpreter is not configured", status_code=422)
    interpreter = Path(cleaned).expanduser()
    if not interpreter.is_absolute():
        raise ProjectPackageError("Project Python interpreter must be an absolute path", status_code=422)
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise ProjectPackageError("Project Python interpreter is unavailable", status_code=404)
    # Keep a virtualenv's python symlink intact. Resolving it can silently turn
    # the selected project runtime back into the base interpreter.
    return Path(os.path.abspath(interpreter))


def _uv_executable() -> str:
    executable = shutil.which("uv")
    if not executable:
        raise ProjectPackageError("uv is required to manage project packages", status_code=503)
    return executable


async def _run(command: list[str], *, timeout: float = 600.0) -> tuple[str, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ProjectPackageError("Project package operation timed out", status_code=504) from exc
    output = stdout.decode("utf-8", errors="replace").strip()
    error = stderr.decode("utf-8", errors="replace").strip()
    if process.returncode != 0:
        raise ProjectPackageError(
            "Project package operation failed",
            status_code=422,
            detail=error or output or f"Command exited with status {process.returncode}",
        )
    return output, error


async def inspect_project_packages(project: dict[str, Any]) -> dict[str, Any]:
    if not str(project.get("python_interpreter_path") or "").strip():
        root = Path(str(project.get("root_path") or "")).expanduser()
        suggested = root / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
        return {
            "project_id": str(project.get("id") or ""),
            "configured": False,
            "python_interpreter_path": None,
            "suggested_python_interpreter_path": str(suggested),
            "aiida_profile": str(project.get("aiida_profile") or "") or None,
            "runtime_ready": False,
            "packages": [],
        }
    interpreter = _validated_interpreter(project.get("python_interpreter_path"))
    inspector = Path(__file__).parents[2] / "aris_core" / "runtime" / "project_package_inspector.py"
    output, _stderr = await _run([str(interpreter), str(inspector)], timeout=30.0)
    try:
        packages = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ProjectPackageError("Project interpreter returned invalid package metadata", status_code=500) from exc
    if not isinstance(packages, list):
        raise ProjectPackageError("Project interpreter returned invalid package metadata", status_code=500)
    names = {str(item.get("name") or "").lower().replace("_", "-") for item in packages if isinstance(item, dict)}
    return {
        "project_id": str(project.get("id") or ""),
        "configured": True,
        "python_interpreter_path": str(interpreter),
        "suggested_python_interpreter_path": None,
        "aiida_profile": str(project.get("aiida_profile") or "") or None,
        "runtime_ready": "aiida-core" in names and "pydantic" in names,
        "packages": packages,
    }


async def create_managed_project_environment(project: dict[str, Any]) -> str:
    root = Path(str(project.get("root_path") or "")).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    environment_root = root / ".venv"
    interpreter = environment_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not interpreter.is_file():
        await _run([_uv_executable(), "venv", str(environment_root), "--python", sys.executable])
    await _run(
        [
            _uv_executable(),
            "pip",
            "install",
            "--python",
            str(interpreter),
            *BASE_RUNTIME_REQUIREMENTS,
        ]
    )
    return str(_validated_interpreter(str(interpreter)))


async def ensure_project_runtime(project: dict[str, Any]) -> dict[str, Any]:
    """Provision the minimum AiiDA worker runtime for a project.

    The worker source is centrally managed by ARIS, but it is executed with
    the selected project's interpreter.  Therefore the project environment
    must contain the AiiDA runtime dependencies even when the MCP server is
    launched independently of the ARIS UI.
    """

    project_data = dict(project)
    interpreter_path = str(project_data.get("python_interpreter_path") or "").strip()
    if not interpreter_path:
        interpreter_path = await create_managed_project_environment(project_data)
        project_data["python_interpreter_path"] = interpreter_path
    else:
        interpreter = _validated_interpreter(interpreter_path)
        project_data["python_interpreter_path"] = str(interpreter)

    inspection = await inspect_project_packages(project_data)
    if not inspection["runtime_ready"]:
        await _run(
            [
                _uv_executable(),
                "pip",
                "install",
                "--python",
                str(project_data["python_interpreter_path"]),
                *BASE_RUNTIME_REQUIREMENTS,
            ]
        )
        await stop_project_worker(project_data)
        inspection = await inspect_project_packages(project_data)
    return inspection


def validate_existing_project_environment(python_interpreter_path: str) -> str:
    return str(_validated_interpreter(python_interpreter_path))


async def install_registry_requirement(project: dict[str, Any], requirement: str) -> dict[str, Any]:
    cleaned = str(requirement or "").strip()
    try:
        parsed = Requirement(cleaned)
    except InvalidRequirement as exc:
        raise ProjectPackageError("Enter a valid Python package requirement", status_code=422) from exc
    interpreter = _validated_interpreter(project.get("python_interpreter_path"))
    await _run([_uv_executable(), "pip", "install", "--python", str(interpreter), str(parsed)])
    await stop_project_worker(project)
    return await inspect_project_packages(project)


async def install_editable_package(project: dict[str, Any], source_path: str) -> dict[str, Any]:
    source = Path(str(source_path or "").strip()).expanduser()
    if not source.is_absolute():
        source = Path(str(project.get("root_path") or "")) / source
    source = source.resolve()
    if not source.is_dir() or not ((source / "pyproject.toml").is_file() or (source / "setup.py").is_file()):
        raise ProjectPackageError("Editable package must contain pyproject.toml or setup.py", status_code=422)
    interpreter = _validated_interpreter(project.get("python_interpreter_path"))
    await _run([_uv_executable(), "pip", "install", "--python", str(interpreter), "--editable", str(source)])
    await stop_project_worker(project)
    return await inspect_project_packages(project)


async def uninstall_project_package(project: dict[str, Any], package_name: str) -> dict[str, Any]:
    cleaned = str(package_name or "").strip()
    if not _PACKAGE_NAME_PATTERN.fullmatch(cleaned):
        raise ProjectPackageError("Invalid package name", status_code=422)
    if cleaned.lower().replace("_", "-") in {"aiida-core", "pydantic"}:
        raise ProjectPackageError("Core project runtime packages cannot be removed", status_code=409)
    interpreter = _validated_interpreter(project.get("python_interpreter_path"))
    await _run([_uv_executable(), "pip", "uninstall", "--python", str(interpreter), cleaned])
    await stop_project_worker(project)
    return await inspect_project_packages(project)


async def stop_project_worker(project: dict[str, Any]) -> None:
    manager = get_worker_process_manager()
    if not isinstance(manager, ProjectWorkerProcessManager):
        return
    await manager.stop_runtime(
        {
            "project_id": str(project.get("id") or ""),
            "python_interpreter_path": str(project.get("python_interpreter_path") or ""),
            "profile_name": str(project.get("aiida_profile") or ""),
        }
    )
