from __future__ import annotations

from datetime import datetime
from pathlib import Path

from playwright.sync_api import BrowserContext, Page


def _safe_name(value: str) -> str:
    keep = []
    for ch in (value or "unknown"):
        if ch.isalnum() or ch in ("-", "_", "."):
            keep.append(ch)
        else:
            keep.append("_")
    return "".join(keep)[:80] or "unknown"


def capture_failure_screenshots(
    context: BrowserContext,
    report_dir: Path,
    *,
    identifier: str,
    reason: str,
) -> list[Path]:
    """
    Capture a PNG of every open browser tab into report_dir/failure-screenshots/.
    Returns paths written (best-effort; never raises).
    """
    out: list[Path] = []
    try:
        shot_dir = report_dir / "failure-screenshots"
        shot_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        reason_bit = _safe_name(reason)[:40]
        ident_bit = _safe_name(identifier)
        for i, page in enumerate(list(context.pages)):
            try:
                if page.is_closed():
                    continue
                try:
                    page.bring_to_front()
                except Exception:
                    pass
                path = shot_dir / f"{ident_bit}_{reason_bit}_{stamp}_tab{i}.png"
                page.screenshot(path=str(path), full_page=True, timeout=30_000)
                out.append(path)
                print(f"[screenshot] {path}")
            except Exception as exc:
                print(f"[screenshot] tab {i} failed: {exc}")
        if not out:
            # Last resort: blank marker file so the folder exists with a note
            note = shot_dir / f"{ident_bit}_{reason_bit}_{stamp}_NO_TABS.txt"
            note.write_text(
                f"No open tabs to screenshot for {identifier}\nreason={reason}\n",
                encoding="utf-8",
            )
    except Exception as exc:
        print(f"[screenshot] capture failed: {exc}")
    return out


def screenshot_note(paths: list[Path]) -> str:
    if not paths:
        return ""
    return " screenshot=" + ";".join(str(p) for p in paths)
