from __future__ import annotations

import os
import shutil
from contextlib import suppress
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _expand_exclude(raw_path: str) -> list[str]:
    cleaned = str(raw_path or "").strip().rstrip("/").rstrip("\\")
    if not cleaned:
        return []

    values = [cleaned]
    path = Path(cleaned)
    with suppress(ValueError):
        relative = path.relative_to(_REPO_ROOT).as_posix()
        if relative not in values:
            values.append(relative)

    expanded: list[str] = []
    for value in values:
        expanded.extend([value, f"{value}/*"])
    return expanded


def collect_reload_excludes(settings: object) -> list[str]:
    seen: set[str] = set()
    excludes: list[str] = []
    candidates = [
        getattr(settings, "ARIS_RUNTIME_ROOT", ""),
        getattr(settings, "ARIS_MEMORY_DIR", ""),
        getattr(settings, "ARIS_PROJECTS_ROOT", ""),
        getattr(settings, "ARIS_SCRIPT_ARCHIVE_DIR", ""),
    ]

    for candidate in candidates:
        for expanded in _expand_exclude(str(candidate)):
            if expanded in seen:
                continue
            seen.add(expanded)
            excludes.append(expanded)

    return excludes


def _bootstrap_config_path(source: Path, target: Path) -> list[dict[str, str]]:
    if not source.exists() or target.exists():
        return []

    if source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(target))
        return [{"source": str(source), "target": str(target)}]

    copied: list[dict[str, str]] = []
    for child in sorted(source.iterdir(), key=lambda item: item.name):
        copied.extend(_bootstrap_config_path(child, target / child.name))
    return copied


def bootstrap_home_config(settings: object) -> list[dict[str, str]]:
    raw_config_root = str(getattr(settings, "ARIS_CONFIG_ROOT", "") or "").strip()
    if not raw_config_root:
        return []
    config_root = Path(raw_config_root).expanduser()

    mappings = [
        (_REPO_ROOT / "config" / "apps", config_root / "apps"),
    ]

    bootstrapped: list[dict[str, str]] = []
    for source, target in mappings:
        bootstrapped.extend(_bootstrap_config_path(source, target))

    return bootstrapped
