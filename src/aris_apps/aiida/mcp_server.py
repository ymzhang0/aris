"""Console entry point for the ARIS AiiDA MCP server."""

from __future__ import annotations

from src.aris_apps.aiida.mcp_facade import build_aiida_mcp_server


def main() -> None:
    build_aiida_mcp_server().run()


if __name__ == "__main__":
    main()
