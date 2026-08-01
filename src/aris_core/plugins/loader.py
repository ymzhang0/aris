from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from fastapi import FastAPI

    from src.aris_core.capabilities import CapabilityRegistry


@dataclass(frozen=True)
class StaticMount:
    url_path: str
    directory: Path
    name: str


class AppManifest(Protocol):
    name: str
    api_prefix: str
    static_mounts: tuple[StaticMount, ...]

    def include_routes(self, app: FastAPI) -> None: ...

    def register_capabilities(self, registry: CapabilityRegistry) -> None: ...

    def register_runtime(self, active_hubs: list[object]) -> None: ...


def _parse_enabled_app_names(raw_names: str | None = None) -> tuple[str, ...]:
    raw = raw_names or os.getenv("ARIS_ENABLED_APPS") or "aiida,materials"
    names = tuple(dict.fromkeys(name.strip() for name in raw.split(",") if name.strip()))
    return names or ("aiida",)


def load_app_manifest(name: str) -> AppManifest:
    module = import_module(f"src.aris_apps.{name}.manifest")
    manifest = getattr(module, "manifest", None)
    if manifest is None:
        raise RuntimeError(f"App manifest not found for '{name}'")
    return manifest


def iter_enabled_app_manifests(raw_names: str | None = None) -> tuple[AppManifest, ...]:
    return tuple(load_app_manifest(name) for name in _parse_enabled_app_names(raw_names))
