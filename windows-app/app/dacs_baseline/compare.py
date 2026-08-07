from __future__ import annotations

import csv
from pathlib import Path


HIT_STATUSES = {
    "CLICK_TO_OPEN",
    "HAS_ORIGINAL_DD1348",
    "AVAILABLE_PDF_OK",
    "AVAILABLE_PDF_OPENED_NO_TEXT",
}


def _load_status_map(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row.get("identifier") or row.get("tcn") or "").strip().upper()
            status = (row.get("status") or row.get("pdfValidation") or "").strip()
            if key:
                out[key] = status
    return out


def compare_runs(before_csv: Path, after_csv: Path) -> dict:
    """Compare two scan-results CSVs; print hit-rate delta."""
    before = _load_status_map(before_csv)
    after = _load_status_map(after_csv)
    keys = sorted(set(before) | set(after))

    b_hits = sum(1 for k in before if before[k] in HIT_STATUSES)
    a_hits = sum(1 for k in after if after[k] in HIT_STATUSES)
    b_n = len(before) or 1
    a_n = len(after) or 1

    improved = []
    regressed = []
    still_miss = []
    still_hit = []
    for k in keys:
        bs = before.get(k, "MISSING_BEFORE")
        as_ = after.get(k, "MISSING_AFTER")
        bh = bs in HIT_STATUSES
        ah = as_ in HIT_STATUSES
        if not bh and ah:
            improved.append(k)
        elif bh and not ah:
            regressed.append(k)
        elif bh and ah:
            still_hit.append(k)
        else:
            still_miss.append(k)

    summary = {
        "before_total": len(before),
        "after_total": len(after),
        "before_hits": b_hits,
        "after_hits": a_hits,
        "before_hit_rate": b_hits / b_n,
        "after_hit_rate": a_hits / a_n,
        "delta_hits": a_hits - b_hits,
        "delta_hit_rate": (a_hits / a_n) - (b_hits / b_n),
        "improved": len(improved),
        "regressed": len(regressed),
        "still_hit": len(still_hit),
        "still_miss": len(still_miss),
        "improved_ids": improved,
        "regressed_ids": regressed,
    }
    return summary


def write_compare_report(summary: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "DACS Original DD1348 hit-rate comparison",
        f"before: {summary['before_hits']}/{summary['before_total']} "
        f"({summary['before_hit_rate']:.1%})",
        f"after:  {summary['after_hits']}/{summary['after_total']} "
        f"({summary['after_hit_rate']:.1%})",
        f"delta hits: {summary['delta_hits']:+d}",
        f"delta rate: {summary['delta_hit_rate']:+.1%}",
        f"improved: {summary['improved']}",
        f"regressed: {summary['regressed']}",
        f"still hit: {summary['still_hit']}",
        f"still miss: {summary['still_miss']}",
        "",
        "Improved identifiers:",
        *[f"  {x}" for x in summary["improved_ids"]],
        "",
        "Regressed identifiers:",
        *[f"  {x}" for x in summary["regressed_ids"]],
    ]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
