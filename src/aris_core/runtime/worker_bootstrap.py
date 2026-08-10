"""Start the centrally bundled AiiDA worker with a project's Python runtime."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: worker_bootstrap.py <aris-aiida-worker-source>")

    worker_root = Path(sys.argv[1]).expanduser().resolve()
    worker_src = worker_root / "src"
    worker_package = worker_src / "aris_aiida_worker"
    if not worker_package.is_dir():
        raise SystemExit(f"invalid bundled worker source: {worker_root}")

    # This runs only inside the isolated child process. The ARIS server never
    # imports project packages or mutates its own sys.path.
    sys.path.insert(0, str(worker_src))
    sys.path.insert(1, str(worker_root))
    sys.path.insert(2, str(Path.cwd()))
    runpy.run_module("aris_aiida_worker", run_name="__main__")


if __name__ == "__main__":
    main()
