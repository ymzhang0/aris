import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WORKSPACE_ROOT = _REPO_ROOT.parent
_DEFAULT_WORKER_ROOT = _WORKSPACE_ROOT / "aiida-worker"
_ARIS_HOME_ROOT = Path.home() / ".aris"
_ARIS_CONFIG_ROOT = _ARIS_HOME_ROOT / "config"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_value(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.getenv(name)
        if raw is None:
            continue
        value = str(raw).strip()
        if value:
            return value
    return default


def _env_flag(*names: str, default: str = "false") -> bool:
    return _env_value(*names, default=default).strip().lower() in _TRUE_VALUES


def _resolve_path(*env_names: str, default_path: Path) -> str:
    explicit = _env_value(*env_names, default="")
    if explicit:
        return explicit
    return str(default_path)


def _resolve_preferred_path(
    *env_names: str,
    preferred_path: Path,
    fallback_path: Path,
) -> str:
    explicit = _env_value(*env_names, default="")
    if explicit:
        return explicit
    if preferred_path.exists():
        return str(preferred_path)
    if fallback_path.exists():
        return str(fallback_path)
    return str(fallback_path)


class Settings(BaseSettings):
    """
    Runtime configuration for the current ARIS codebase.
    """

    ENGINE_TYPE: str = _env_value("ARIS_ENGINE_TYPE", default="")
    DEPS_CLASS: str = _env_value("ARIS_DEPS_CLASS", default="")
    GEMINI_API_KEY: str = _env_value("GEMINI_API_KEY", default="your-key-here")
    DEFAULT_MODEL: str = _env_value("ARIS_DEFAULT_MODEL", default="gemini-flash-latest")
    GEMINI_API_VERSION: str = _env_value("ARIS_GEMINI_API_VERSION", default="v1beta")
    GEMINI_MAX_OUTPUT_TOKENS: int = int(
        _env_value("ARIS_GEMINI_MAX_OUTPUT_TOKENS", "GEMINI_MAX_OUTPUT_TOKENS", default="32768")
    )
    GEMINI_UNAVAILABLE_RETRIES: int = int(
        _env_value("ARIS_GEMINI_UNAVAILABLE_RETRIES", default="2")
    )
    GEMINI_UNAVAILABLE_RETRY_BACKOFF_SECONDS: float = float(
        _env_value(
            "ARIS_GEMINI_UNAVAILABLE_RETRY_BACKOFF_SECONDS",
            default="2.0",
        )
    )

    ARIS_RUNTIME_ROOT: str = _resolve_path(
        "ARIS_RUNTIME_ROOT",
        default_path=_ARIS_HOME_ROOT,
    )
    ARIS_MEMORY_DIR: str = _env_value(
        "ARIS_MEMORY_DIR",
        default=str(Path(ARIS_RUNTIME_ROOT) / "memories"),
    )
    ARIS_CONFIG_ROOT: str = _env_value(
        "ARIS_CONFIG_ROOT",
        default=str(_ARIS_CONFIG_ROOT),
    )
    ARIS_PRESETS_FILE: str = _env_value(
        "ARIS_PRESETS_FILE",
        default=str(_ARIS_CONFIG_ROOT / "apps/aiida/presets.yaml"),
    )
    ARIS_PROJECTS_ROOT: str = _env_value(
        "ARIS_PROJECTS_ROOT",
        default=str(_ARIS_HOME_ROOT / "projects"),
    )
    ARIS_SCRIPT_ARCHIVE_DIR: str = _env_value(
        "ARIS_SCRIPT_ARCHIVE_DIR",
        default=str(Path(ARIS_RUNTIME_ROOT) / "scripts"),
    )
    ARIS_WORKER_RUNTIME_ENABLED: bool = _env_flag(
        "ARIS_WORKER_RUNTIME_ENABLED",
        default="true",
    )
    ARIS_WORKER_DEFAULT_PROFILE: str = _env_value(
        "ARIS_WORKER_DEFAULT_PROFILE",
        "AIIDA_PROFILE",
        default="",
    )
    ARIS_WORKER_PACKAGE_SOURCE: str = _resolve_path(
        "ARIS_WORKER_PACKAGE_SOURCE",
        default_path=_DEFAULT_WORKER_ROOT,
    )
    ARIS_LOCAL_ACTOR_ID: str = _env_value(
        "ARIS_LOCAL_ACTOR_ID",
        default="local-user",
    )
    ARIS_LOCAL_ROLE: str = _env_value(
        "ARIS_LOCAL_ROLE",
        default="owner",
    )
    ARIS_POLICY_MODEL_FILE: str = _resolve_preferred_path(
        "ARIS_POLICY_MODEL_FILE",
        preferred_path=_ARIS_CONFIG_ROOT / "policy" / "model.conf",
        fallback_path=_REPO_ROOT / "config" / "policy" / "model.conf",
    )
    ARIS_POLICY_FILE: str = _resolve_preferred_path(
        "ARIS_POLICY_FILE",
        preferred_path=_ARIS_CONFIG_ROOT / "policy" / "policy.csv",
        fallback_path=_REPO_ROOT / "config" / "policy" / "policy.csv",
    )

    PRODUCTION_MODE: bool = _env_flag("ARIS_PRODUCTION_MODE", "PRODUCTION_MODE", default="false")

    HTTPS_PROXY: str = _env_value("HTTPS_PROXY", default="")
    HTTP_PROXY: str = _env_value("HTTP_PROXY", default="")
    ARIS_USE_OUTBOUND_PROXY: bool = _env_flag("ARIS_USE_OUTBOUND_PROXY", default="false")
    ARIS_FRONTEND_ORIGINS: str = _env_value(
        "ARIS_FRONTEND_ORIGINS",
        default="http://localhost:5173,http://127.0.0.1:5173,https://aiida.yiming-zhang.com",
    )
    FRONTEND_DIST_DIR: str = _resolve_path(
        "ARIS_FRONTEND_DIST_DIR",
        default_path=_REPO_ROOT / "frontend" / "dist",
    )
    FRONTEND_ASSETS_DIR: str = _resolve_path(
        "ARIS_FRONTEND_ASSETS_DIR",
        default_path=_REPO_ROOT / "frontend" / "dist" / "assets",
    )
    FRONTEND_INDEX_FILE: str = _resolve_path(
        "ARIS_FRONTEND_INDEX_FILE",
        default_path=_REPO_ROOT / "frontend" / "dist" / "index.html",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_file_encoding="utf-8",
    )


settings = Settings()

__all__ = ["Settings", "settings"]
