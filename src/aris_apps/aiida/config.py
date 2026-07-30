from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_ARIS_HOME_ROOT = Path.home() / ".aris"
_ARIS_CONFIG_ROOT = os.getenv("ARIS_CONFIG_ROOT", str(_ARIS_HOME_ROOT / "config"))


def _resolve_preferred_path(env_name: str, preferred_path: Path, fallback_path: Path) -> str:
    explicit = os.getenv(env_name, "").strip()
    if explicit:
        return explicit
    if preferred_path.exists():
        return str(preferred_path)
    return str(fallback_path)


@dataclass(frozen=True)
class AiiDAEngineSettings:
    bridge_environment: str = "Managed AiiDA runtime"
    offline_worker_message: str = os.getenv(
        "AIIDA_OFFLINE_WORKER_MESSAGE",
        "ARIS could not start its managed AiiDA runtime.",
    )



    @property
    def presets_file(self) -> str:
        return _resolve_preferred_path(
            "ARIS_AIIDA_PRESETS_FILE",
            preferred_path=Path(_ARIS_CONFIG_ROOT) / "apps" / "aiida" / "presets.yaml",
            fallback_path=_REPO_ROOT / "config" / "apps" / "aiida" / "presets.yaml",
        )

    @property
    def settings_file(self) -> str:
        return _resolve_preferred_path(
            "ARIS_AIIDA_SETTINGS_FILE",
            preferred_path=Path(_ARIS_CONFIG_ROOT) / "apps" / "aiida" / "settings.yaml",
            fallback_path=_REPO_ROOT / "config" / "apps" / "aiida" / "settings.yaml",
        )

    @property
    def specializations_root(self) -> str:
        return _resolve_preferred_path(
            "ARIS_AIIDA_SPECIALIZATIONS_ROOT",
            preferred_path=Path(_ARIS_CONFIG_ROOT) / "apps" / "aiida" / "specializations",
            fallback_path=_REPO_ROOT / "config" / "apps" / "aiida" / "specializations",
        )


aiida_engine_settings = AiiDAEngineSettings()
