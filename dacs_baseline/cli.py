from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

from . import __version__
from .compare import compare_runs, write_compare_report
from .efts import click_cac_if_present, dismiss_scip_modals, wait_for_efts_ready
from .input_path import input_dir, resolve_input
from .scanner import run_baseline
from .spreadsheet import infer_search_by, load_identifiers
from .throttle import Throttle


DEFAULT_EFTS = "https://test.scip.dsca.mil/NewEftsWeb/"
# Gov-cloud / CAC paths can be slow; Playwright default is 30s.
DEFAULT_NAV_TIMEOUT_MS = 300_000  # 5 minutes


def _load_config(path: Path | None) -> dict:
    if not path:
        return {}
    if not path.exists():
        raise SystemExit(f"Config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit("Config must be a YAML mapping")
    return data


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dacs-baseline",
        description=(
            "Standalone DACS Original DD1348 IRRD baseline scanner for EFTS. "
            "Uses system Chrome for CAC/client-cert on gov-cloud VMs."
        ),
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Optional YAML config (default: ./config.yaml if present)",
    )

    sub = p.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Run before or after baseline scan")
    scan.add_argument(
        "--input",
        type=Path,
        default=None,
        help="xlsx/csv/txt of shipment identifiers (default: auto from ./input/)",
    )
    scan.add_argument(
        "--efts-url",
        default=None,
        help=f"EFTS base URL (default: {DEFAULT_EFTS})",
    )
    scan.add_argument(
        "--label",
        default="baseline",
        help="Run label used in output filenames (e.g. before, after)",
    )
    scan.add_argument(
        "--search-by",
        choices=["auto", "tcn", "document", "requisition"],
        default=None,
        help="List Search radio. auto uses Identifier Type / trailing *",
    )
    scan.add_argument("--start-index", type=int, default=0, help="Skip first N identifiers")
    scan.add_argument("--max", type=int, default=None, help="Only scan first N after start-index")
    scan.add_argument(
        "--delay-seconds",
        type=float,
        default=None,
        help="Pause after each Details open (throttle). User choice.",
    )
    scan.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="After every N opens, take a longer pause (0=off). User choice.",
    )
    scan.add_argument(
        "--batch-pause-seconds",
        type=float,
        default=None,
        help="Seconds to pause between batches. User choice.",
    )
    scan.add_argument(
        "--list-search-wait-seconds",
        type=int,
        default=None,
        help="Max wait for List Search Results (N)",
    )
    scan.add_argument(
        "--out-dir",
        type=Path,
        default=Path("reports"),
        help="Output directory for CSVs",
    )
    scan.add_argument(
        "--user-data-dir",
        type=Path,
        default=None,
        help="Chrome profile dir (keeps CAC session across runs)",
    )
    scan.add_argument(
        "--cac-timeout-seconds",
        type=int,
        default=600,
        help="How long to wait for operator CAC PIN / cert selection",
    )
    scan.add_argument(
        "--navigation-timeout-seconds",
        type=int,
        default=None,
        help="Playwright page/navigation timeout (default: 300 = 5 minutes)",
    )
    scan.add_argument(
        "--headed",
        action="store_true",
        default=True,
        help=argparse.SUPPRESS,
    )

    cmp_ = sub.add_parser("compare", help="Compare before vs after scan-results CSVs")
    cmp_.add_argument("--before", type=Path, required=True)
    cmp_.add_argument("--after", type=Path, required=True)
    cmp_.add_argument(
        "--out",
        type=Path,
        default=Path("reports/hit-rate-compare.txt"),
    )

    prep = sub.add_parser("prep-ids", help="Extract unique identifiers from spreadsheet to .txt")
    prep.add_argument("--input", type=Path, default=None)
    prep.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output txt (default: ./input/identifiers.txt)",
    )

    return p


def _resolve_src(args: argparse.Namespace, cfg: dict) -> Path:
    try:
        return resolve_input(args.input, cfg.get("input"))
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc


def cmd_prep(args: argparse.Namespace, cfg: dict) -> int:
    src = _resolve_src(args, cfg)
    out = args.out or (input_dir() / "identifiers.txt")
    rows = load_identifiers(src, unique=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(r.identifier for r in rows) + "\n", encoding="utf-8")
    search = infer_search_by(rows, cfg.get("search_by", "auto"))
    print(f"Source: {src}")
    print(f"Wrote {len(rows)} unique identifiers -> {out}")
    print(f"Inferred List Search mode: {search}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    summary = compare_runs(args.before, args.after)
    write_compare_report(summary, args.out)
    print(json.dumps({k: v for k, v in summary.items() if not k.endswith("_ids")}, indent=2))
    print(f"Report: {args.out}")
    return 0


def cmd_scan(args: argparse.Namespace, cfg: dict) -> int:
    src = _resolve_src(args, cfg)

    efts_url = args.efts_url or cfg.get("efts_url") or DEFAULT_EFTS
    user_data = args.user_data_dir or Path(cfg.get("user_data_dir") or "user-data")
    search_override = args.search_by or cfg.get("search_by") or "requisition"

    delay = (
        args.delay_seconds
        if args.delay_seconds is not None
        else float(cfg.get("delay_seconds", 2.0))
    )
    batch_size = (
        args.batch_size if args.batch_size is not None else int(cfg.get("batch_size", 0))
    )
    batch_pause = (
        args.batch_pause_seconds
        if args.batch_pause_seconds is not None
        else float(cfg.get("batch_pause_seconds", 30))
    )
    wait_sec = (
        args.list_search_wait_seconds
        if args.list_search_wait_seconds is not None
        else int(cfg.get("list_search_wait_seconds", 900))
    )
    nav_timeout_ms = int(
        (
            args.navigation_timeout_seconds
            if args.navigation_timeout_seconds is not None
            else cfg.get("navigation_timeout_seconds", DEFAULT_NAV_TIMEOUT_MS // 1000)
        )
    ) * 1000

    rows = load_identifiers(src, unique=True)
    if args.start_index:
        rows = rows[args.start_index :]
    if args.max is not None:
        rows = rows[: args.max]
    if not rows:
        raise SystemExit("No identifiers to scan")

    search_by = infer_search_by(rows, search_override)
    throttle = Throttle(delay, batch_size, batch_pause)

    print(f"Input: {src}")
    print(f"Identifiers: {len(rows)} | search-by: {search_by} | label: {args.label}")
    print(
        f"Throttle: delay={delay}s batch_size={batch_size} "
        f"batch_pause={batch_pause}s"
    )
    print(f"EFTS: {efts_url}")
    print("Chrome will open — complete CAC/cert PIN when prompted.")

    user_data.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        # System Chrome picks up Windows CAC / client certificates.
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(user_data.resolve()),
            channel="chrome",
            headless=False,
            accept_downloads=True,
            ignore_https_errors=False,
            args=[
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        page = context.pages[0] if context.pages else context.new_page()
        context.set_default_timeout(nav_timeout_ms)
        context.set_default_navigation_timeout(nav_timeout_ms)
        print(f"Navigation timeout: {nav_timeout_ms // 1000}s")
        page.goto(
            efts_url,
            wait_until="domcontentloaded",
            timeout=nav_timeout_ms,
        )
        dismiss_scip_modals(page)
        click_cac_if_present(page)
        wait_for_efts_ready(page, timeout_ms=args.cac_timeout_seconds * 1000)

        summary = run_baseline(
            list_page=page,
            context=context,
            efts_base=efts_url,
            rows=rows,
            search_by=search_by,
            out_dir=args.out_dir,
            throttle=throttle,
            list_search_wait_seconds=wait_sec,
            label=args.label,
        )
        context.close()

    print(json.dumps(summary, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg_path = args.config if args.config.exists() else None
    cfg = _load_config(cfg_path)

    if args.command == "prep-ids":
        return cmd_prep(args, cfg)
    if args.command == "compare":
        return cmd_compare(args)
    if args.command == "scan":
        return cmd_scan(args, cfg)
    parser.error(f"Unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
