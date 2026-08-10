"""Emit installed distribution metadata for one Python interpreter."""

from __future__ import annotations

import importlib.metadata
import json


def main() -> None:
    packages: list[dict[str, object]] = []
    for distribution in importlib.metadata.distributions():
        name = str(distribution.metadata.get("Name") or "").strip()
        if not name:
            continue
        direct_url: dict[str, object] = {}
        raw_direct_url = distribution.read_text("direct_url.json")
        if raw_direct_url:
            try:
                parsed = json.loads(raw_direct_url)
                if isinstance(parsed, dict):
                    direct_url = parsed
            except json.JSONDecodeError:
                direct_url = {}
        directory_info = direct_url.get("dir_info")
        editable = isinstance(directory_info, dict) and directory_info.get("editable") is True
        packages.append(
            {
                "name": name,
                "version": distribution.version,
                "editable": editable,
                "source": str(direct_url.get("url") or "") or None,
            }
        )
    packages.sort(key=lambda item: str(item["name"]).lower())
    print(json.dumps(packages, ensure_ascii=True))


if __name__ == "__main__":
    main()
