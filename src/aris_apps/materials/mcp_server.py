from __future__ import annotations

from src.aris_apps.materials.mcp_facade import build_materials_mcp_server


def main() -> None:
    build_materials_mcp_server().run()


if __name__ == "__main__":
    main()
