"""
Windows app entry point for DACS DD1348 Baseline Scanner.

Used by PyInstaller and by Launch-DACS-Baseline.bat (python mode).
When frozen, extra CLI args (e.g. scan ...) are forwarded to the CLI so the
GUI can spawn the same .exe for a scan run.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def main() -> int:
    root = _app_root()
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    for rel in ("input", "reports/dd1348-irrd", "user-data"):
        (root / rel).mkdir(parents=True, exist_ok=True)

    # Packaged exe invoked as: DACS-DD1348-Baseline.exe scan --label before ...
    if len(sys.argv) > 1 and sys.argv[1] in {
        "scan",
        "compare",
        "prep-ids",
        "--version",
        "-h",
        "--help",
    }:
        from dacs_baseline.cli import main as cli_main

        return int(cli_main(sys.argv[1:]) or 0)

    from dacs_baseline.app import main as app_main

    return int(app_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
