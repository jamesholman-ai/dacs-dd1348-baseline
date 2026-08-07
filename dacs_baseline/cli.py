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
from .file_picker import pick_input_file
from .input_path import default_identifiers_path, input_dir, resolve_input
from .line_select import apply_line_filters
from .scanner import run_baseline
from .spreadsheet import infer_search_by, load_identifiers
from .throttle import Throttle
from .user_settings import load_settings


DEFAULT_EFTS = "https://test.scip.dsca.mil/NewEftsWeb/"
# Gov-cloud / CAC paths can be slow; Playwright default is 30s.
DEFAULT_NAV_TIMEOUT_MS = 300_000  # 5 minutes
DEFAULT_INPUT_NAME = "identifiers-full-462.txt"
SAMPLE_INPUT_NAME = "identifiers-sample-10.txt"


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
        help=f"xlsx/csv/txt of shipment identifiers (default: file picker, or input/{DEFAULT_INPUT_NAME})",
    )
    scan.add_argument(
        "--pick-input",
        action="store_true",
        default=True,
        help="Open a file-picker dialog to choose the ID list (default: on)",
    )
    scan.add_argument(
        "--no-pick-input",
        action="store_true",
        help="Skip file picker; use --input / config / identifiers-full-462.txt",
    )
    scan.add_argument(
        "--sample-10",
        action="store_true",
        help=f"Use input/{SAMPLE_INPUT_NAME} (10 IDs) without a picker",
    )
    scan.add_argument(
        "--efts-url",
        default=None,
        help=f"EFTS base URL (default: {DEFAULT_EFTS})",
    )
    scan.add_argument(
        "--label",
        default="baseline",
        help="Run type tag stored in the summary (e.g. before, after)",
    )
    scan.add_argument(
        "--report-name",
        default=None,
        help=(
            "Name for this report folder under --out-dir. "
            "If omitted, a timestamp folder is created (YYYYMMDD_HHMMSS)."
        ),
    )
    scan.add_argument(
        "--resume",
        nargs="?",
        const="__AUTO__",
        default=None,
        help=(
            "Resume an early-stopped test and update that same report. "
            "Optional value: report folder path or name under --out-dir. "
            "With no value, resumes the latest early-stopped report."
        ),
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
        "--lines",
        default=None,
        help='Only these 1-based lines from the loaded list (e.g. "5-8" or "1,3,10")',
    )
    scan.add_argument(
        "--skip-lines",
        default=None,
        help='Skip these 1-based lines (e.g. "2,4" or "10-12")',
    )
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
        default=Path("reports") / "dd1348-irrd",
        help="Report root folder (default: reports/dd1348-irrd/<report-name>/)",
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
        help="How long to wait for initial operator CAC PIN / cert selection",
    )
    scan.add_argument(
        "--midrun-cac-timeout-seconds",
        type=float,
        default=None,
        help=(
            "If a CAC/login prompt appears mid-scan (not the initial login), "
            "wait this many seconds then stop and publish partial results "
            "(default: 300 = 5 minutes)"
        ),
    )
    scan.add_argument(
        "--details-tab-timeout-seconds",
        type=float,
        default=None,
        help=(
            "After clicking a List Search result, wait this long for the Details "
            "tab to open and Document Center / Original DD1348 to populate "
            "(default: 300 = 5 minutes)"
        ),
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
        help=f"Output txt (default: ./input/{DEFAULT_INPUT_NAME})",
    )

    return p


def _resolve_src(args: argparse.Namespace, cfg: dict) -> Path:
    # Explicit path wins
    if getattr(args, "input", None) is not None:
        try:
            return resolve_input(args.input, None)
        except FileNotFoundError as exc:
            raise SystemExit(str(exc)) from exc

    # Quick 10-ID sample
    if getattr(args, "sample_10", False):
        sample = input_dir() / SAMPLE_INPUT_NAME
        if not sample.exists():
            raise SystemExit(f"Sample file not found: {sample}")
        return sample

    use_picker = getattr(args, "pick_input", True) and not getattr(
        args, "no_pick_input", False
    )
    # prep-ids has no pick flags
    if hasattr(args, "no_pick_input") and use_picker:
        print("Select the identifier list in the file dialog...")
        return pick_input_file(initial_dir=input_dir())

    try:
        configured = cfg.get("input") or DEFAULT_INPUT_NAME
        return resolve_input(None, configured)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc


def cmd_prep(args: argparse.Namespace, cfg: dict) -> int:
    src = _resolve_src(args, cfg)
    out = args.out or default_identifiers_path()
    rows = load_identifiers(src, unique=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(r.identifier for r in rows) + "\n", encoding="utf-8")
    # Keep identifiers.txt in sync as the working upload copy
    working = input_dir() / "identifiers.txt"
    if working.resolve() != out.resolve():
        working.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
    search = infer_search_by(rows, cfg.get("search_by", "auto"))
    print(f"Source: {src}")
    print(f"Wrote {len(rows)} unique identifiers -> {out}")
    if working.resolve() != out.resolve():
        print(f"Also synced -> {working}")
    print(f"Inferred List Search mode: {search}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    summary = compare_runs(args.before, args.after)
    write_compare_report(summary, args.out)
    print(json.dumps({k: v for k, v in summary.items() if not k.endswith("_ids")}, indent=2))
    print(f"Report: {args.out}")
    return 0


def cmd_scan(args: argparse.Namespace, cfg: dict) -> int:
    from .run_state import find_resumable_report, load_state
    from .spreadsheet import ShipmentRow

    user = load_settings()
    out_dir = args.out_dir
    if str(out_dir) == str(Path("reports") / "dd1348-irrd") and user.get("reports_dir"):
        out_dir = Path(user["reports_dir"])

    resume_from = getattr(args, "resume", None)
    src: Path | None = None
    rows: list = []
    before_count = 0

    if resume_from is not None:
        # Resume: prefer planned IDs from run-state; optional input only for extras
        try:
            report_dir = find_resumable_report(out_dir, resume_from)
        except FileNotFoundError as exc:
            raise SystemExit(str(exc)) from exc
        state = load_state(report_dir) or {}
        planned = [str(x) for x in (state.get("planned_identifiers") or [])]
        if planned:
            rows = [ShipmentRow(i, None, "TCN", n) for n, i in enumerate(planned, 1)]
            before_count = len(rows)
            src = report_dir / "list-search-upload.txt"
            print(f"[resume] Loaded {len(rows)} planned IDs from {report_dir}")
        else:
            # Fall back to input file
            args.no_pick_input = True
            src = _resolve_src(args, cfg)
            rows = load_identifiers(src, unique=True)
            before_count = len(rows)
    else:
        src = _resolve_src(args, cfg)
        keep_file_order = bool(args.lines or args.skip_lines)
        rows = load_identifiers(src, unique=not keep_file_order)
        before_count = len(rows)
        rows = apply_line_filters(
            rows,
            start_index=args.start_index or 0,
            max_count=args.max,
            lines=args.lines,
            skip_lines=args.skip_lines,
        )
        if keep_file_order:
            seen: set[str] = set()
            deduped = []
            for r in rows:
                key = r.identifier.upper()
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(r)
            rows = deduped

    if not rows:
        raise SystemExit("No identifiers to scan after line filters")

    efts_url = (
        args.efts_url
        or cfg.get("efts_url")
        or user.get("efts_url")
        or DEFAULT_EFTS
    )
    user_data = args.user_data_dir or Path(
        cfg.get("user_data_dir") or user.get("user_data_dir") or "user-data"
    )
    search_override = args.search_by or cfg.get("search_by") or user.get("search_by") or "tcn"

    delay = (
        args.delay_seconds
        if args.delay_seconds is not None
        else float(cfg.get("delay_seconds", user.get("delay_seconds", 2.0)))
    )
    batch_size = (
        args.batch_size
        if args.batch_size is not None
        else int(cfg.get("batch_size", user.get("batch_size", 0)))
    )
    batch_pause = (
        args.batch_pause_seconds
        if args.batch_pause_seconds is not None
        else float(cfg.get("batch_pause_seconds", user.get("batch_pause_seconds", 30)))
    )
    wait_sec = (
        args.list_search_wait_seconds
        if args.list_search_wait_seconds is not None
        else int(cfg.get("list_search_wait_seconds", 900))
    )
    midrun_cac = (
        args.midrun_cac_timeout_seconds
        if args.midrun_cac_timeout_seconds is not None
        else float(
            cfg.get(
                "midrun_cac_timeout_seconds",
                user.get("midrun_cac_timeout_seconds", 300),
            )
        )
    )
    details_tab_timeout = (
        args.details_tab_timeout_seconds
        if args.details_tab_timeout_seconds is not None
        else float(
            cfg.get(
                "details_tab_timeout_seconds",
                user.get("details_tab_timeout_seconds", 300),
            )
        )
    )
    nav_timeout_ms = int(
        (
            args.navigation_timeout_seconds
            if args.navigation_timeout_seconds is not None
            else cfg.get(
                "navigation_timeout_seconds",
                user.get("navigation_timeout_seconds", DEFAULT_NAV_TIMEOUT_MS // 1000),
            )
        )
    ) * 1000

    search_by = infer_search_by(rows, search_override)
    throttle = Throttle(delay, batch_size, batch_pause)

    report_name = getattr(args, "report_name", None)
    print(f"Input: {src}")
    print(
        f"Identifiers: {len(rows)} (from {before_count} loaded) | "
        f"search-by: {search_by} | label: {args.label}"
    )
    if report_name:
        print(f"Report name: {report_name}")
    else:
        print("Report name: (timestamp will be used)")
    if resume_from is not None:
        print(f"Resume: {resume_from}")
    if args.lines:
        print(f"Lines include: {args.lines}")
    if args.skip_lines:
        print(f"Lines skip: {args.skip_lines}")
    print(
        f"Throttle: delay={delay}s batch_size={batch_size} "
        f"batch_pause={batch_pause}s"
    )
    print(f"Mid-run CAC failsafe: {int(midrun_cac)}s then stop + publish")
    print(
        f"Details tab wait: {int(details_tab_timeout)}s "
        "(open + Document Center / IRRD populated)"
    )
    print(f"EFTS: {efts_url}")
    print("Chrome will open — complete CAC/cert PIN when prompted.")

    user_data.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

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
            out_dir=out_dir,
            throttle=throttle,
            list_search_wait_seconds=wait_sec,
            label=args.label,
            report_name=report_name,
            resume_from=resume_from,
            midrun_cac_timeout_seconds=midrun_cac,
            details_tab_timeout_seconds=details_tab_timeout,
        )
        context.close()

    print(json.dumps(summary, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    # Double-click / no-args → GUI launcher
    if argv is None and len(sys.argv) == 1:
        from .app import main as app_main

        return app_main()

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
