import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(os.getcwd())
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


def _resolve_path(*env_names: str, default_path: Path, legacy_paths: tuple[Path, ...] = ()) -> str:
    explicit = _env_value(*env_names, default="")
    if explicit:
        return explicit
    if default_path.exists():
        return str(default_path)
    for legacy_path in legacy_paths:
        if legacy_path.exists():
            return str(legacy_path)
    return str(default_path)


def _resolve_preferred_path(
    *env_names: str,
    preferred_path: Path,
    fallback_path: Path,
    legacy_paths: tuple[Path, ...] = (),
) -> str:
    explicit = _env_value(*env_names, default="")
    if explicit:
        return explicit
    if preferred_path.exists():
        return str(preferred_path)
    if fallback_path.exists():
        return str(fallback_path)
    for legacy_path in legacy_paths:
        if legacy_path.exists():
            return str(legacy_path)
    return str(fallback_path)


def _path_variants(raw_path: str) -> set[str]:
    cleaned = str(raw_path or "").strip().rstrip("/").rstrip("\\")
    if not cleaned:
        return set()

    path = Path(cleaned).expanduser()
    lexical_absolute = path if path.is_absolute() else (_REPO_ROOT / path)
    variants = {
        cleaned,
        lexical_absolute.as_posix(),
    }

    try:
        variants.add(lexical_absolute.relative_to(_REPO_ROOT).as_posix())
    except ValueError:
        pass

    try:
        variants.add(lexical_absolute.resolve(strict=False).as_posix())
    except OSError:
        pass

    return {value for value in variants if value}


def _normalize_runtime_path(raw_path: str, *, canonical_path: Path, legacy_paths: tuple[Path, ...]) -> str:
    raw_variants = _path_variants(raw_path)
    canonical = str(canonical_path)
    if not raw_variants:
        return canonical

    canonical_variants = _path_variants(canonical)
    if raw_variants & canonical_variants:
        return canonical

    for legacy_path in legacy_paths:
        if raw_variants & _path_variants(str(legacy_path)):
            return canonical

    return str(raw_path)


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
        legacy_paths=(
            _REPO_ROOT / "runtime",
        ),
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
        "ARIS_AIIDA_PRESETS_FILE",
        default=_resolve_preferred_path(
            "ARIS_AIIDA_PRESETS_FILE",
            preferred_path=_ARIS_CONFIG_ROOT / "apps" / "aiida" / "presets.yaml",
            fallback_path=_REPO_ROOT / "config" / "apps" / "aiida" / "presets.yaml",
            legacy_paths=(
                _REPO_ROOT / "config" / "aiida_presets.yaml",
            ),
        ),
    )
    ARIS_AIIDA_SETTINGS_FILE: str = _env_value(
        "ARIS_AIIDA_SETTINGS_FILE",
        default=_resolve_preferred_path(
            "ARIS_AIIDA_SETTINGS_FILE",
            preferred_path=_ARIS_CONFIG_ROOT / "apps" / "aiida" / "settings.yaml",
            fallback_path=_REPO_ROOT / "config" / "apps" / "aiida" / "settings.yaml",
            legacy_paths=(
                _REPO_ROOT / "config" / "aiida_settings.yaml",
            ),
        ),
    )
    ARIS_AIIDA_SPECIALIZATIONS_ROOT: str = _resolve_preferred_path(
        "ARIS_AIIDA_SPECIALIZATIONS_ROOT",
        preferred_path=_ARIS_CONFIG_ROOT / "apps" / "aiida" / "specializations",
        fallback_path=_REPO_ROOT / "config" / "apps" / "aiida" / "specializations",
        legacy_paths=(
            _REPO_ROOT / "config" / "specializations",
        ),
    )
    ARIS_PROJECTS_ROOT: str = _env_value(
        "ARIS_PROJECTS_ROOT",
        default=str(_ARIS_HOME_ROOT / "projects"),
    )
    ARIS_SCRIPT_ARCHIVE_DIR: str = _env_value(
        "ARIS_SCRIPT_ARCHIVE_DIR",
        default=str(Path(ARIS_RUNTIME_ROOT) / "scripts"),
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

    ARIS_DEBUG_LEVEL: str = _env_value("ARIS_DEBUG_LEVEL", default="default")
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
        default_path=_REPO_ROOT / "apps" / "web" / "dist",
        legacy_paths=(
            _REPO_ROOT / "frontend" / "dist",
        ),
    )
    FRONTEND_ASSETS_DIR: str = _resolve_path(
        "ARIS_FRONTEND_ASSETS_DIR",
        default_path=_REPO_ROOT / "apps" / "web" / "dist" / "assets",
        legacy_paths=(
            _REPO_ROOT / "frontend" / "dist" / "assets",
        ),
    )
    FRONTEND_INDEX_FILE: str = _resolve_path(
        "ARIS_FRONTEND_INDEX_FILE",
        default_path=_REPO_ROOT / "apps" / "web" / "dist" / "index.html",
        legacy_paths=(
            _REPO_ROOT / "frontend" / "dist" / "index.html",
        ),
    )

    def model_post_init(self, __context) -> None:
        raw_runtime_root = Path(self.ARIS_RUNTIME_ROOT)
        object.__setattr__(
            self,
            "ARIS_RUNTIME_ROOT",
            _normalize_runtime_path(
                self.ARIS_RUNTIME_ROOT,
                canonical_path=_ARIS_HOME_ROOT,
                legacy_paths=(
                    _REPO_ROOT / "runtime",
                ),
            ),
        )
        runtime_root = Path(self.ARIS_RUNTIME_ROOT)
        object.__setattr__(
            self,
            "ARIS_MEMORY_DIR",
            _normalize_runtime_path(
                self.ARIS_MEMORY_DIR,
                canonical_path=runtime_root / "memories",
                legacy_paths=(
                    raw_runtime_root / "memories",
                    _REPO_ROOT / "runtime" / "memories",
                    _REPO_ROOT / "default",
                    _REPO_ROOT / "data" / "memories",
                    _REPO_ROOT / "engines" / "aiida" / "data" / "memories",
                ),
            ),
        )
        object.__setattr__(
            self,
            "ARIS_PROJECTS_ROOT",
            _normalize_runtime_path(
                self.ARIS_PROJECTS_ROOT,
                canonical_path=_ARIS_HOME_ROOT / "projects",
                legacy_paths=(
                    runtime_root / "projects",
                    _REPO_ROOT / "data" / "projects",
                ),
            ),
        )
        object.__setattr__(
            self,
            "ARIS_SCRIPT_ARCHIVE_DIR",
            _normalize_runtime_path(
                self.ARIS_SCRIPT_ARCHIVE_DIR,
                canonical_path=runtime_root / "scripts",
                legacy_paths=(
                    raw_runtime_root / "scripts",
                    _REPO_ROOT / "runtime" / "scripts",
                    _REPO_ROOT / "engines" / "aiida" / "data" / "scripts",
                ),
            ),
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_file_encoding="utf-8",
    )


settings = Settings()

__all__ = ["Settings", "settings"]
