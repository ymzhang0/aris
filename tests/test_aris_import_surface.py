from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("GOOGLE_API_KEY", "dummy")

from src.aris_apps.aiida.agent.researcher import aiida_researcher
from src.aris_apps.aiida.api.router import router as aiida_router
from src.aris_apps.aiida.chat import get_chat_snapshot
from src.aris_apps.aiida.client import get_aiida_worker_client
from src import aris_core
from src.aris_core.config import Settings, settings
from src.aris_core.config import runtime as runtime_config
from src.aris_core.deps import BaseARISDeps
from src.aris_core.memory import ARISMemoryState, JSONMemory
from src.aris_core.protocols import Executor, Perceptor
from src.aris_core.schema import ARISResponse, Action, Observation


def test_aris_core_surface_is_available() -> None:
    assert aris_core.Settings is Settings
    assert settings.FRONTEND_INDEX_FILE
    assert Path(settings.FRONTEND_INDEX_FILE).as_posix().endswith("frontend/dist/index.html")
    assert Path(settings.ARIS_RUNTIME_ROOT).as_posix().endswith(".aris")
    assert settings.ARIS_MEMORY_DIR
    assert Path(settings.ARIS_MEMORY_DIR).is_absolute()
    assert Path(settings.ARIS_CONFIG_ROOT).as_posix().endswith(".aris/config")
    assert settings.ARIS_PROJECTS_ROOT
    assert Path(settings.ARIS_PROJECTS_ROOT).is_absolute()
    assert Path(settings.ARIS_PRESETS_FILE).as_posix().endswith("config/apps/aiida/presets.yaml")
    assert Path(settings.ARIS_AIIDA_SETTINGS_FILE).as_posix().endswith("config/apps/aiida/settings.yaml")
    assert settings.ARIS_SCRIPT_ARCHIVE_DIR
    assert Path(settings.ARIS_SCRIPT_ARCHIVE_DIR).is_absolute()
    assert BaseARISDeps.__name__ == "BaseARISDeps"
    assert JSONMemory.__name__ == "JSONMemory"
    assert ARISMemoryState.__name__ == "ARISMemoryState"
    assert Executor.__name__ == "Executor"
    assert Perceptor.__name__ == "Perceptor"
    assert Observation(raw="ok").source == "default"
    assert Action(name="noop").payload == {}
    assert ARISResponse.__name__ == "ARISResponse"
    assert ARISResponse(answer="ok", thought_process=[]).is_successful is True


def test_aris_response_requires_submission_request_for_batch_mode_without_draft() -> None:
    with pytest.raises(ValueError):
        ARISResponse(answer="ok", thought_process=[], task_mode="batch")


def test_aris_response_allows_batch_mode_when_submission_request_present() -> None:
    response = ARISResponse(
        answer="ok",
        thought_process=[],
        task_mode="batch",
        submission_request={
            "mode": "batch",
            "workchain": "quantumespresso.pw.base",
            "structure_pks": [11],
            "code": "pw@localhost",
            "protocol": "moderate",
            "parameter_grid": {"scale_factor": [0.98, 1.0, 1.02]},
        },
    )

    assert response.task_mode == "batch"


def test_aris_aiida_surface_is_available() -> None:
    assert aiida_researcher is not None
    assert callable(get_aiida_worker_client)
    assert callable(get_chat_snapshot)
    assert aiida_router is not None


def test_api_entrypoints_import_with_aris_paths() -> None:
    from apps.api.main import app as api_app
    from src.app_api import app as source_app

    assert api_app is source_app
    assert api_app.title == "ARIS Central Hub"


def test_json_memory_defaults_to_runtime_settings(tmp_path) -> None:
    original_dir = settings.ARIS_MEMORY_DIR
    settings.ARIS_MEMORY_DIR = str(tmp_path)
    try:
        memory = JSONMemory(namespace="aris-default-path")
        assert Path(memory.file_path).parent == tmp_path
    finally:
        settings.ARIS_MEMORY_DIR = original_dir


def test_json_memory_uses_canonical_namespace_state(tmp_path) -> None:
    memory = JSONMemory(namespace="aris_v2_global", storage_path=str(tmp_path))
    memory.set_kv("migrated", True)

    reloaded = JSONMemory(namespace="aris_v2_global", storage_path=str(tmp_path))

    assert reloaded.file_path.endswith("history_aris_v2_global.json")
    assert reloaded.get_kv("migrated") is True


def test_bootstrap_home_config_copies_repo_defaults(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "config" / "apps" / "aiida" / "specializations").mkdir(parents=True)
    (repo_root / "config" / "apps" / "aiida" / "presets.yaml").write_text("presets: []\n", encoding="utf-8")
    (repo_root / "config" / "apps" / "aiida" / "settings.yaml").write_text("settings: {}\n", encoding="utf-8")
    (repo_root / "config" / "apps" / "aiida" / "specializations" / "qe.yaml").write_text(
        "name: qe\n",
        encoding="utf-8",
    )
    (repo_root / "ecosystem.config.js").write_text("module.exports = {};\n", encoding="utf-8")

    home_root = tmp_path / ".aris"
    fake_settings = SimpleNamespace(
        ARIS_CONFIG_ROOT=str(home_root / "config"),
    )

    monkeypatch.setattr(runtime_config, "_REPO_ROOT", repo_root)

    bootstrapped = runtime_config.bootstrap_home_config(fake_settings)

    assert bootstrapped
    assert (home_root / "config" / "apps" / "aiida" / "presets.yaml").is_file()
    assert (home_root / "config" / "apps" / "aiida" / "settings.yaml").is_file()
    assert (home_root / "config" / "apps" / "aiida" / "specializations" / "qe.yaml").is_file()
    assert (home_root / "config" / "pm2" / "ecosystem.config.js").is_file()
    assert Path(fake_settings.ARIS_PRESETS_FILE).as_posix().endswith(".aris/config/apps/aiida/presets.yaml")
    assert Path(fake_settings.ARIS_AIIDA_SETTINGS_FILE).as_posix().endswith(
        ".aris/config/apps/aiida/settings.yaml"
    )
    assert Path(fake_settings.ARIS_AIIDA_SPECIALIZATIONS_ROOT).as_posix().endswith(
        ".aris/config/apps/aiida/specializations"
    )
