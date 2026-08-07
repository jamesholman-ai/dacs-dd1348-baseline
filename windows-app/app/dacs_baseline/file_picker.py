from __future__ import annotations

from pathlib import Path


def pick_input_file(
    *,
    initial_dir: Path | None = None,
    title: str = "Select shipment identifier list (txt / csv / xlsx)",
) -> Path:
    """
    Open a native file dialog so the operator can choose the ID list.
    Uses tkinter (stdlib) — works on Windows gov-cloud VMs.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # pragma: no cover
        raise SystemExit(
            f"File picker unavailable ({exc}). Pass --input path instead."
        ) from exc

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        start = str((initial_dir or Path.cwd() / "input").resolve())
        path = filedialog.askopenfilename(
            parent=root,
            title=title,
            initialdir=start,
            filetypes=[
                ("Identifier lists", "*.txt;*.csv;*.xlsx;*.xlsm"),
                ("Text", "*.txt"),
                ("CSV", "*.csv"),
                ("Excel", "*.xlsx;*.xlsm"),
                ("All files", "*.*"),
            ],
        )
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    if not path:
        raise SystemExit("No input file selected — cancelled.")
    chosen = Path(path)
    if not chosen.exists():
        raise SystemExit(f"Selected file not found: {chosen}")
    return chosen
