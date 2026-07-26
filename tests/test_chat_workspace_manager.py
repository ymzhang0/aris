from __future__ import annotations

from pathlib import Path

import pytest

from src.aris_apps.aiida.chat import service as chat_service
from src.aris_apps.aiida.chat.workspace_manager import ChatWorkspaceManager


def _manager(tmp_path: Path) -> ChatWorkspaceManager:
    return ChatWorkspaceManager(lambda: tmp_path / "managed")


def test_ensure_project_workspace_creates_one_shared_project_layout(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    project = {"id": "project-1"}

    root = manager.ensure_project_workspace_dir(project)

    assert root == tmp_path / "managed" / "project-1"
    assert project["root_path"] == str(root)
    assert (root / "codes").is_dir()
    assert (root / "data").is_dir()
    assert not (root / "sessions").exists()


def test_ensure_session_workspace_uses_shared_project_root(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    project = {"id": "project-1"}
    root = manager.ensure_project_workspace_dir(project)
    session = {
        "id": "session-1",
        "project_id": "project-1",
        "session_slug": "si-bands",
    }

    workspace = manager.ensure_session_workspace_dir(project, session)

    assert workspace == str(root)
    assert session["workspace_path"] == str(root)
    assert not (root / "sessions").exists()


def test_project_cleanup_preserves_custom_root_but_removes_managed_root(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    custom_root = tmp_path / "custom-project"
    (custom_root / "codes").mkdir(parents=True)
    (custom_root / "sessions" / "old").mkdir(parents=True)
    custom_project = {"id": "custom", "root_path": str(custom_root)}

    managed_project = {"id": "managed"}
    managed_root = manager.ensure_project_workspace_dir(managed_project)

    manager.cleanup_project_workspace_dir(custom_project)
    manager.cleanup_project_workspace_dir(managed_project)

    assert custom_root.is_dir()
    assert (custom_root / "codes").is_dir()
    assert (custom_root / "sessions").is_dir()
    assert not managed_root.exists()


def test_workspace_target_rejects_parent_traversal_and_symlink_escape(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()

    with pytest.raises(ValueError, match="escapes"):
        ChatWorkspaceManager.resolve_workspace_target_path(root, "../outside/file.txt")

    symlink = root / "linked"
    try:
        symlink.symlink_to(outside, target_is_directory=True)
    except OSError:
        return
    with pytest.raises(ValueError, match="escapes"):
        ChatWorkspaceManager.resolve_workspace_target_path(root, "linked/file.txt")


def test_project_root_validation_and_environment_mode(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    invalid_root = tmp_path / "project-file"
    invalid_root.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ValueError, match="points to a file"):
        manager.validate_new_project_root_path(invalid_root, project_id="project-1")

    managed_project = {
        "id": "project-1",
        "root_path": str(tmp_path / "managed" / "project-1"),
    }
    custom_project = {"id": "project-2", "root_path": str(tmp_path / "custom")}
    assert manager.project_default_environment_mode(managed_project) == "worker-default"
    assert manager.project_default_environment_mode(custom_project) == "project-auto"


def test_managed_project_id_cannot_escape_managed_root(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    target = manager.managed_project_root("../../outside")

    assert target.parent == (tmp_path / "managed").resolve()
    assert target.name.startswith("project-")
    assert manager.is_path_within(target, tmp_path / "managed")


def test_chat_service_uses_workspace_manager_path_validation() -> None:
    assert isinstance(chat_service._CHAT_WORKSPACE_MANAGER, ChatWorkspaceManager)
    assert chat_service._resolve_workspace_target_path(
        Path("/tmp/aris-workspace-test"),
        "codes/job.py",
    ) == Path("/tmp/aris-workspace-test/codes/job.py").resolve()
