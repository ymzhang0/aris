from __future__ import annotations

from pathlib import Path


def test_legacy_runtime_paths_resolve_to_runtime_root() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    runtime_root = repo_root / "runtime"

    legacy_roots = (repo_root / "engines" / "aiida" / "data",)

    for legacy_root in legacy_roots:
        assert legacy_root.exists()
        assert legacy_root.resolve() == runtime_root.resolve()


def test_repository_does_not_recreate_legacy_memory_directory() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    canonical_memories = repo_root / "runtime" / "memories"
    legacy_memories = repo_root / "engines" / "aiida" / "data" / "memories"

    assert not canonical_memories.exists()
    assert not legacy_memories.exists()
