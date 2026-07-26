from __future__ import annotations

import importlib
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from src.aris_core.logging import log_event, setup_logging

# 1. Load environment variables at the very beginning (Proxy, API Keys)
load_dotenv()
setup_logging(default_level="INFO")
logger.info(log_event("logging.ready"))

from src.aris_core.config import settings
from src.aris_core.config.runtime import (
    bootstrap_home_config,
    collect_reload_excludes,
)
from src.aris_core.memory import JSONMemory
from src.aris_core.plugins import iter_enabled_app_manifests

# Global state container for long-lived objects
state = {}
# Dynamic hub registry.
ACTIVE_HUBS = []
DEFAULT_ENGINE = "aiida"
APP_MANIFESTS = iter_enabled_app_manifests()
APP_MANIFESTS_BY_NAME = {manifest.name: manifest for manifest in APP_MANIFESTS}


def _configure_proxy_environment() -> None:
    """Normalize proxy environment variables from ARIS settings."""
    use_proxy = bool(settings.ARIS_USE_OUTBOUND_PROXY)
    http_proxy = str(settings.HTTP_PROXY or "").strip() if use_proxy else ""
    https_proxy = str(settings.HTTPS_PROXY or "").strip() if use_proxy else ""

    # Clear or set environment variables
    for env_key in ("HTTP_PROXY", "http_proxy"):
        if http_proxy:
            os.environ[env_key] = http_proxy
        else:
            os.environ.pop(env_key, None)

    for env_key in ("HTTPS_PROXY", "https_proxy"):
        if https_proxy:
            os.environ[env_key] = https_proxy
        else:
            os.environ.pop(env_key, None)

    # Ensure localhost traffic is never proxied
    no_proxy_raw = str(os.getenv("NO_PROXY") or os.getenv("no_proxy") or "").strip()
    no_proxy_items = {item.strip() for item in no_proxy_raw.split(",") if item.strip()}
    no_proxy_items.update({"127.0.0.1", "localhost", "::1"})
    no_proxy_value = ",".join(sorted(no_proxy_items))
    os.environ["NO_PROXY"] = no_proxy_value
    os.environ["no_proxy"] = no_proxy_value

    logger.info(
        log_event(
            "network.proxy.configured",
            use_proxy=use_proxy,
            http_proxy=bool(http_proxy),
            https_proxy=bool(https_proxy),
            no_proxy=no_proxy_value,
        )
    )


_configure_proxy_environment()


def _get_engine_manifest(engine_name: str):
    manifest = APP_MANIFESTS_BY_NAME.get(engine_name)
    if manifest is None:
        available = ", ".join(sorted(APP_MANIFESTS_BY_NAME))
        raise RuntimeError(f"Unsupported engine '{engine_name}'. Enabled app manifests: {available}")
    return manifest


# ============================================================
# 🧬 Lifespan Management
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles startup and shutdown logic for the ARIS Hub.
    """
    logger.info(log_event("hub.startup.begin"))

    bootstrapped_config_entries = bootstrap_home_config(settings)
    if bootstrapped_config_entries:
        logger.info(
            log_event(
                "runtime.config.bootstrapped",
                count=len(bootstrapped_config_entries),
            )
        )

    # Initialize Global Memory
    memory = JSONMemory(
        namespace="aris_v2_global",
        storage_path=settings.ARIS_MEMORY_DIR,
    )
    state["memory"] = memory
    app.state.memory = memory
    
    # Dynamically load the engine-specific agent and deps
    engine_name = (settings.ENGINE_TYPE or "").strip() or DEFAULT_ENGINE
    try:
        engine_manifest = _get_engine_manifest(engine_name)
        agent_module = importlib.import_module(engine_manifest.agent_module)
        agent = getattr(agent_module, f"{engine_name}_researcher")

        runtime_factory = getattr(agent_module, "build_agent_runtime", None)
        if not callable(runtime_factory):
            raise RuntimeError(f"Engine '{engine_name}' does not provide an agent runtime")
        agent_runtime = runtime_factory(agent)
        state["agent_runtime"] = agent_runtime
        app.state.agent_runtime = agent_runtime
        
        deps_module = importlib.import_module(engine_manifest.deps_module)
        configured_deps_class = (settings.DEPS_CLASS or "").strip()
        if configured_deps_class and hasattr(deps_module, configured_deps_class):
            deps_class_name = configured_deps_class
        else:
            deps_class_name = getattr(deps_module, "DEFAULT_DEPS_CLASS", "AiiDADeps")
        deps_class = getattr(deps_module, deps_class_name)
        state["deps_class"] = deps_class
        app.state.deps_class = deps_class
        
        logger.info(
            log_event(
                "engine.agent.online",
                runtime=type(agent_runtime).__name__,
            )
        )

        for hub in ACTIVE_HUBS:
            if hasattr(hub, 'start'):
                hub.start()
                
    except Exception as e:
        logger.exception(log_event("engine.bootstrap.failed", engine=engine_name, error=str(e)))
  
    yield
    logger.info(log_event("hub.shutdown.begin"))
    # Cleanup logic
    state.clear()
    logger.info(log_event("hub.shutdown.done"))

# ============================================================
# 🛠️ FastAPI Application Setup
# ============================================================
app = FastAPI(
    title="ARIS Central Hub",
    description="Agentic scientific research hub powered by PydanticAI",
    lifespan=lifespan
)

FRONTEND_DIST_DIR = settings.FRONTEND_DIST_DIR
FRONTEND_ASSETS_DIR = settings.FRONTEND_ASSETS_DIR
FRONTEND_INDEX_FILE = settings.FRONTEND_INDEX_FILE

for manifest in APP_MANIFESTS:
    for static_mount in manifest.static_mounts:
        if not static_mount.directory.is_dir():
            logger.warning(log_event("app.static.missing", app=manifest.name, path=str(static_mount.directory)))
            continue
        app.mount(static_mount.url_path, StaticFiles(directory=str(static_mount.directory)), name=static_mount.name)

if os.path.isdir(FRONTEND_ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="assets")
else:
    logger.warning(log_event("frontend.assets.missing", path=FRONTEND_ASSETS_DIR))


def _get_cors_origins() -> list[str]:
    required = {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://aris.yiming-zhang.com",
    }
    raw = settings.ARIS_FRONTEND_ORIGINS or ""
    values = {item.strip() for item in raw.split(",") if item.strip()}
    return sorted(values | required)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# 🚩 Engine-Specific Route Mounting
# ============================================================
def mount_enabled_apps(app: FastAPI) -> None:
    for manifest in APP_MANIFESTS:
        try:
            manifest.include_routes(app)
            manifest.register_runtime(ACTIVE_HUBS)
            logger.info(log_event("engine.registry.registered", engine=manifest.name))
        except Exception as exc:  # noqa: BLE001
            logger.exception(log_event("engine.registry.failed", engine=manifest.name, error=str(exc)))


mount_enabled_apps(app)


@app.get("/api/health")
async def healthcheck():
    return {"status": "ok"}


# ============================================================
# 🛣️ Core Agent Endpoint (The Cyclic Hub)
# ============================================================

@app.get("/{full_path:path}", include_in_schema=False)
async def spa_catch_all(full_path: str = ""):
    if full_path.startswith("api") or full_path.startswith("assets") or full_path.startswith("static"):
        return HTMLResponse("Not Found", status_code=404)

    if not os.path.isfile(FRONTEND_INDEX_FILE):
        logger.warning(
            log_event(
                "frontend.index.missing",
                path=FRONTEND_INDEX_FILE,
                dist=FRONTEND_DIST_DIR,
            )
        )
        return HTMLResponse("Frontend build not found.", status_code=404)

    return FileResponse(FRONTEND_INDEX_FILE)
# ============================================================
# 🏁 Execution Entry
# ============================================================
if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Run ARIS API server.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument(
        "--log-level",
        default=os.getenv("ARIS_LOG_LEVEL", "INFO"),
        choices=["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"],
    )
    args = parser.parse_args()

    runtime_log_level = str(args.log_level).upper()
    os.environ["ARIS_LOG_LEVEL"] = runtime_log_level
    setup_logging(default_level=runtime_log_level)
    logger.info(
        log_event(
            "server.run",
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level=runtime_log_level,
        )
    )
    reload_excludes = collect_reload_excludes(settings) if args.reload else None
    uvicorn.run(
        "apps.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_excludes=reload_excludes,
        log_config=None,
    )
