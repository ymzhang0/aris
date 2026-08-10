from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from src.aris_apps.aiida import project_packages


def test_unconfigured_project_reports_managed_environment_target(tmp_path: Path) -> None:
    payload = asyncio.run(
        project_packages.inspect_project_packages(
            {"id": "project-a", "root_path": str(tmp_path), "python_interpreter_path": None}
        )
    )

    assert payload["configured"] is False
    assert payload["runtime_ready"] is False
    assert payload["suggested_python_interpreter_path"].endswith(".venv/bin/python")


def test_package_inspection_runs_inside_selected_interpreter(tmp_path: Path) -> None:
    payload = asyncio.run(
        project_packages.inspect_project_packages(
            {
                "id": "project-a",
                "root_path": str(tmp_path),
                "python_interpreter_path": sys.executable,
                "aiida_profile": "dev",
            }
        )
    )

    assert payload["configured"] is True
    assert Path(payload["python_interpreter_path"]).samefile(sys.executable)
    assert payload["aiida_profile"] == "dev"
    assert isinstance(payload["packages"], list)


def test_managed_environment_installs_only_runtime_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    async def fake_run(command: list[str], *, timeout: float = 600.0):
        commands.append(command)
        if len(command) > 1 and command[1] == "venv":
            interpreter = tmp_path / ".venv" / "bin" / "python"
            interpreter.parent.mkdir(parents=True)
            interpreter.write_text("#!/bin/sh\n", encoding="utf-8")
            interpreter.chmod(0o755)
        return "", ""

    monkeypatch.setattr(project_packages, "_run", fake_run)
    monkeypatch.setattr(project_packages, "_uv_executable", lambda: "/usr/bin/uv")

    interpreter = asyncio.run(
        project_packages.create_managed_project_environment(
            {"id": "project-a", "root_path": str(tmp_path)}
        )
    )

    assert interpreter == str((tmp_path / ".venv" / "bin" / "python").resolve())
    assert commands[0][1] == "venv"
    assert "aiida-core>=2.7.3" in commands[1]
    assert "pydantic>=2.10" in commands[1]
    assert all("aris-aiida-worker" not in item for item in commands[1])


def test_ensure_project_runtime_installs_missing_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    async def fake_run(command: list[str], *, timeout: float = 600.0):
        commands.append(command)
        return "", ""

    inspections = iter([
        {"runtime_ready": False, "python_interpreter_path": str(Path(sys.executable))},
        {"runtime_ready": True, "python_interpreter_path": str(Path(sys.executable))},
    ])

    async def fake_inspect(_project):
        return next(inspections)

    async def fake_stop(_project):
        return None

    monkeypatch.setattr(project_packages, "_run", fake_run)
    monkeypatch.setattr(project_packages, "_uv_executable", lambda: "/usr/bin/uv")
    monkeypatch.setattr(project_packages, "inspect_project_packages", fake_inspect)
    monkeypatch.setattr(project_packages, "stop_project_worker", fake_stop)

    result = asyncio.run(
        project_packages.ensure_project_runtime(
            {
                "id": "project-a",
                "root_path": str(tmp_path),
                "python_interpreter_path": str(Path(sys.executable)),
            }
        )
    )

    assert result["runtime_ready"] is True
    assert commands == [[
        "/usr/bin/uv",
        "pip",
        "install",
        "--python",
        str(Path(sys.executable)),
        "aiida-core>=2.7.3",
        "pydantic>=2.10",
    ]]


def test_editable_install_uses_explicit_local_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_root = tmp_path / "local-plugin"
    package_root.mkdir()
    (package_root / "pyproject.toml").write_text("[project]\nname='local-plugin'\nversion='0.1'\n")
    commands: list[list[str]] = []

    async def fake_run(command: list[str], *, timeout: float = 600.0):
        commands.append(command)
        return "", ""

    async def fake_stop(_project):
        return None

    async def fake_inspect(_project):
        return {"packages": []}

    monkeypatch.setattr(project_packages, "_run", fake_run)
    monkeypatch.setattr(project_packages, "_uv_executable", lambda: "/usr/bin/uv")
    monkeypatch.setattr(project_packages, "stop_project_worker", fake_stop)
    monkeypatch.setattr(project_packages, "inspect_project_packages", fake_inspect)

    asyncio.run(
        project_packages.install_editable_package(
            {
                "id": "project-a",
                "root_path": str(tmp_path),
                "python_interpreter_path": sys.executable,
            },
            str(package_root),
        )
    )

    assert commands == [[
        "/usr/bin/uv",
        "pip",
        "install",
        "--python",
        str(Path(sys.executable)),
        "--editable",
        str(package_root.resolve()),
    ]]


def test_core_runtime_packages_cannot_be_uninstalled(tmp_path: Path) -> None:
    with pytest.raises(project_packages.ProjectPackageError, match="cannot be removed"):
        asyncio.run(
            project_packages.uninstall_project_package(
                {
                    "id": "project-a",
                    "root_path": str(tmp_path),
                    "python_interpreter_path": sys.executable,
                },
                "aiida-core",
            )
        )
