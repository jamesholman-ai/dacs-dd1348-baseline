from __future__ import annotations

import shutil
from pathlib import Path


def safe_copy(src: Path, dst: Path) -> Path:
    """
    Copy src -> dst. If dst is locked (Excel/PermissionError), write a
    stamped alternate next to it and return that path.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(src, dst)
        return dst
    except PermissionError:
        stamp = src.stem.split("_")[-1] if "_" in src.stem else "locked"
        alt = dst.with_name(f"{dst.stem}_OPEN_ME_{stamp}{dst.suffix}")
        try:
            shutil.copyfile(src, alt)
            print(
                f"[report] Permission denied writing {dst.name} "
                f"(close Excel if open). Wrote {alt.name} instead."
            )
            return alt
        except Exception as exc:
            print(f"[report] Could not copy {src.name}: {exc}")
            return src
    except Exception as exc:
        print(f"[report] Copy failed {src.name} -> {dst.name}: {exc}")
        return src


def safe_write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(text, encoding="utf-8")
        return path
    except PermissionError:
        alt = path.with_name(f"{path.stem}_OPEN_ME{path.suffix}")
        alt.write_text(text, encoding="utf-8")
        print(
            f"[report] Permission denied writing {path.name}. "
            f"Wrote {alt.name} instead."
        )
        return alt
