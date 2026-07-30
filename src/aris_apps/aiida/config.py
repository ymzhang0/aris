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
    default_bridge_url: str = os.getenv("AIIDA_DEFAULT_BRIDGE_URL", "http://127.0.0.1:8001")
    bridge_url: str = os.getenv("AIIDA_BRIDGE_URL", "")
    bridge_environment: str = os.getenv("AIIDA_BRIDGE_ENVIRONMENT", "Remote Bridge")
    offline_worker_message: str = os.getenv(
        "AIIDA_OFFLINE_WORKER_MESSAGE",
        "AiiDA Worker is offline, please ensure the bridge is running on port 8001.",
    )

    @property
    def resolved_bridge_url(self) -> str:
        raw = str(self.bridge_url or self.default_bridge_url).strip()
        return raw if raw else self.default_bridge_url

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
