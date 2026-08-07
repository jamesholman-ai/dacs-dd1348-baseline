from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


STATE_NAME = "run-state.json"
SKIP_STATUSES = {
    "NOT_SCANNED_EARLY_STOP",
    "IN_PROGRESS",
    "TCN_NOT_FOUND_IN_LIST_SEARCH",
    "NOT_IN_LIST_SEARCH_RESULTS",  # legacy
    "",
}


def timestamp_name() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def sanitize_report_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", (name or "").strip())
    cleaned = cleaned.strip(" .")
    return cleaned or timestamp_name()


def resolve_report_name(report_name: str | None) -> str:
    if report_name and str(report_name).strip():
        return sanitize_report_name(str(report_name))
    return timestamp_name()


def resolve_report_dir(out_dir: Path, report_name: str) -> Path:
    return out_dir / sanitize_report_name(report_name)


def state_path(report_dir: Path) -> Path:
    return report_dir / STATE_NAME


def load_state(report_dir: Path) -> dict[str, Any] | None:
    path = state_path(report_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def save_state(report_dir: Path, data: dict[str, Any]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = state_path(report_dir)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def load_result_rows(all_results_csv: Path) -> list[dict[str, str]]:
    if not all_results_csv.exists():
        return []
    with all_results_csv.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def completed_identifiers(rows: list[dict[str, str]]) -> set[str]:
    done: set[str] = set()
    for row in rows:
        ident = (row.get("identifier") or "").strip()
        status = (row.get("status") or "").strip()
        if not ident:
            continue
        if status in SKIP_STATUSES or status.upper() == "NOT_SCANNED_EARLY_STOP":
            continue
        done.add(ident.upper())
    return done


def recount_from_rows(rows: list[dict[str, str]]) -> dict[str, int]:
    hits = unavailable = errors = scanned = 0
    for row in rows:
        status = (row.get("status") or "").strip()
        has = (row.get("has_original_dd1348") or "").strip().lower()
        if status in SKIP_STATUSES or status.upper() in {
            "NOT_SCANNED_EARLY_STOP",
            "IN_PROGRESS",
            "TCN_NOT_FOUND_IN_LIST_SEARCH",
            "NOT_IN_LIST_SEARCH_RESULTS",
        }:
            continue
        if status == "NOT_IN_LIST_SEARCH_RESULTS":
            continue
        scanned += 1
        if has == "yes" or status in {
            "CLICK_TO_OPEN",
            "HAS_ORIGINAL_DD1348",
            "AVAILABLE_PDF_OK",
            "AVAILABLE_PDF_OPENED_NO_TEXT",
        }:
            hits += 1
        elif has == "no" or status == "UNAVAILABLE":
            unavailable += 1
        else:
            errors += 1
    return {
        "scanned": scanned,
        "hits": hits,
        "unavailable": unavailable,
        "errors": errors,
    }


def find_resumable_report(out_dir: Path, name_or_path: str | None = None) -> Path:
    """
    Resolve a report folder to resume.
    - Absolute/relative path to a report dir
    - Report folder name under out_dir
    - None / __AUTO__: latest run-state.json with stopped_early=true
    """
    if name_or_path and name_or_path not in {"__AUTO__", "auto", "latest"}:
        candidate = Path(name_or_path)
        if candidate.exists() and candidate.is_dir():
            return candidate.resolve()
        under = out_dir / sanitize_report_name(name_or_path)
        if under.exists():
            return under.resolve()
        raise FileNotFoundError(
            f"Resume report not found: {name_or_path} (looked in {under})"
        )

    if not out_dir.exists():
        raise FileNotFoundError(f"No reports under {out_dir}")

    candidates: list[tuple[float, Path]] = []
    for path in out_dir.rglob(STATE_NAME):
        report_dir = path.parent
        state = load_state(report_dir) or {}
        if not state.get("stopped_early"):
            continue
        mtime = path.stat().st_mtime
        candidates.append((mtime, report_dir))

    if not candidates:
        # Fall back: any folder with all-results.csv mentioning early stop
        for path in out_dir.rglob("all-results.csv"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "NOT_SCANNED_EARLY_STOP" in text:
                candidates.append((path.stat().st_mtime, path.parent))

    if not candidates:
        raise FileNotFoundError(
            f"No early-stopped report found under {out_dir}. "
            "Pass --resume <report-folder-or-name>."
        )
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1].resolve()
