"""Console entry points for the ARIS AiiDA MCP server."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.aris_apps.aiida.mcp_facade import build_aiida_mcp_server
from src.aris_apps.aiida.mcp_context import AiiDAProjectCatalog
from src.aris_core.runtime import (
    ProjectWorkerProcessManager,
    configure_worker_process_manager,
)


def _first_non_empty(*values: Any) -> str:
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned
    return ""

def _configure_standalone_runtime(project_catalog: AiiDAProjectCatalog) -> None:
    worker_source = Path(
        _first_non_empty(
            os.environ.get("ARIS_WORKER_PACKAGE_SOURCE"),
            Path(__file__).resolve().parents[4] / "aiida-worker",
        )
    ).expanduser().resolve()
    manager = ProjectWorkerProcessManager(
        runtime_context_provider=lambda: project_catalog.context_for(),
        worker_package_source=worker_source,
        request_timeout=60.0,
    )
    configure_worker_process_manager(manager)


def main() -> None:
    project_catalog = AiiDAProjectCatalog()
    _configure_standalone_runtime(project_catalog)
    build_aiida_mcp_server(project_catalog=project_catalog).run()


def main_http() -> None:
    """Run the same MCP server over streamable HTTP for ChatGPT connections."""

    project_catalog = AiiDAProjectCatalog()
    _configure_standalone_runtime(project_catalog)
    host = os.environ.get("ARIS_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("ARIS_MCP_PORT", "8000"))
    build_aiida_mcp_server(project_catalog=project_catalog).run(
        transport="streamable-http",
        host=host,
        port=port,
        path="/mcp",
    )


if __name__ == "__main__":
    main()
