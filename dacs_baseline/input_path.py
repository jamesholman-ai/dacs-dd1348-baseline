from __future__ import annotations

from pathlib import Path

INPUT_DIR_NAME = "input"
FULL_IDENTIFIERS_NAME = "identifiers-full-462.txt"
PREFERRED_NAMES = (
    FULL_IDENTIFIERS_NAME,
    "identifiers-sample-10.txt",
    "identifiers.txt",
    "identifiers.csv",
    "QAReqsThatExistInDACS.xlsx",
)
EXTENSIONS = (".xlsx", ".xlsm", ".csv", ".txt")


def default_identifiers_path(base: Path | None = None) -> Path:
    """Canonical full 462-ID list used by scan/prep defaults."""
    return input_dir(base) / FULL_IDENTIFIERS_NAME


def repo_root() -> Path:
    """Project root (parent of the dacs_baseline package)."""
    return Path(__file__).resolve().parent.parent


def input_dir(base: Path | None = None) -> Path:
    root = base or repo_root()
    # Prefer CWD/input when running from the cloned repo; fall back to package root.
    cwd_input = Path.cwd() / INPUT_DIR_NAME
    if cwd_input.is_dir():
        return cwd_input
    return root / INPUT_DIR_NAME


def resolve_input(
    explicit: Path | None = None,
    config_value: str | Path | None = None,
    *,
    base: Path | None = None,
) -> Path:
    """
    Resolve the shipment-identifier input file.

    Order:
      1. --input path
      2. config `input` (file or directory under ./input)
      3. Preferred filenames in ./input/
      4. Newest .xlsx/.csv/.txt in ./input/
    """
    if explicit is not None:
        path = Path(explicit)
        if not path.exists():
            raise FileNotFoundError(f"Input not found: {path}")
        return path

    if config_value:
        path = Path(config_value)
        if not path.is_absolute():
            # Relative paths are from CWD first, then input/
            candidates = [Path.cwd() / path, input_dir(base) / path, path]
            for c in candidates:
                if c.exists():
                    return c if c.is_file() else _pick_from_dir(c)
            raise FileNotFoundError(f"Input not found from config: {config_value}")
        if path.is_dir():
            return _pick_from_dir(path)
        if path.exists():
            return path
        raise FileNotFoundError(f"Input not found from config: {config_value}")

    folder = input_dir(base)
    if not folder.is_dir():
        raise FileNotFoundError(
            f"No input folder at {folder}. Create it and drop an xlsx/csv/txt there."
        )
    return _pick_from_dir(folder)


def _pick_from_dir(folder: Path) -> Path:
    for name in PREFERRED_NAMES:
        candidate = folder / name
        if candidate.is_file():
            return candidate

    files = [
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in EXTENSIONS and not p.name.startswith(".")
    ]
    if not files:
        raise FileNotFoundError(
            f"No xlsx/csv/txt found in {folder}. "
            "Place Jeff's spreadsheet or identifiers.txt there."
        )
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]
