from __future__ import annotations

from .spreadsheet import ShipmentRow


def parse_line_set(spec: str) -> set[int]:
    """
    Parse 1-based line specs like: 1,3,5-8
    Returns a set of 1-based line numbers.
    """
    lines: set[int] = set()
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a.strip()), int(b.strip())
            if end < start:
                start, end = end, start
            lines.update(range(start, end + 1))
        else:
            lines.add(int(part))
    return {n for n in lines if n >= 1}


def apply_line_filters(
    rows: list[ShipmentRow],
    *,
    start_index: int = 0,
    max_count: int | None = None,
    lines: str | None = None,
    skip_lines: str | None = None,
) -> list[ShipmentRow]:
    """
    Filter identifier rows.

    - start_index: 0-based offset (existing CLI)
    - max_count: take first N after other filters
    - lines: 1-based include list/ranges (e.g. "5-8" or "1,3,10")
    - skip_lines: 1-based exclude list/ranges
    """
    indexed = list(enumerate(rows, start=1))  # 1-based line numbers in source file order

    if lines:
        include = parse_line_set(lines)
        indexed = [(n, r) for n, r in indexed if n in include]

    if skip_lines:
        exclude = parse_line_set(skip_lines)
        indexed = [(n, r) for n, r in indexed if n not in exclude]

    # start_index is 0-based over the remaining list
    if start_index:
        indexed = indexed[start_index:]

    if max_count is not None:
        indexed = indexed[:max_count]

    return [r for _, r in indexed]
