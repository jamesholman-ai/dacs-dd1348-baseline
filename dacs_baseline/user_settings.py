from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SETTINGS_NAME = "user-settings.json"


def settings_path(root: Path | None = None) -> Path:
    base = root or Path.cwd()
    return base / SETTINGS_NAME


def default_settings(root: Path | None = None) -> dict[str, Any]:
    base = (root or Path.cwd()).resolve()
    return {
        "setup_complete": False,
        "work_dir": str(base),
        "input_dir": str(base / "input"),
        "reports_dir": str(base / "reports" / "dd1348-irrd"),
        "user_data_dir": str(base / "user-data"),
        "efts_url": "https://test.scip.dsca.mil/NewEftsWeb/",
        "default_label": "before",
        "delay_seconds": 2.0,
        "batch_size": 25,
        "batch_pause_seconds": 45,
        "midrun_cac_timeout_seconds": 300,
        "details_tab_timeout_seconds": 300,
        "cac_timeout_seconds": 600,
        "navigation_timeout_seconds": 300,
        "search_by": "tcn",
    }


def load_settings(root: Path | None = None) -> dict[str, Any]:
    path = settings_path(root)
    base = default_settings(root)
    if not path.exists():
        return base
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return base
    if not isinstance(data, dict):
        return base
    merged = {**base, **data}
    return merged


def save_settings(data: dict[str, Any], root: Path | None = None) -> Path:
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def needs_setup(root: Path | None = None) -> bool:
    s = load_settings(root)
    return not bool(s.get("setup_complete"))
