from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from playwright.sync_api import BrowserContext, Page

from . import efts
from .cac_guard import wait_out_midrun_cac
from .input_path import input_dir
from .reporting import safe_copy, safe_write_text
from .run_state import (
    completed_identifiers,
    find_resumable_report,
    load_result_rows,
    load_state,
    recount_from_rows,
    resolve_report_dir,
    resolve_report_name,
    save_state,
)
from .spreadsheet import ShipmentRow, write_upload_txt
from .throttle import Throttle


# Default report root (new folder for DD1348 Click-to-Open vs Unavailable)
DEFAULT_REPORT_DIR = Path("reports") / "dd1348-irrd"

HIT_STATUSES = {
    "CLICK_TO_OPEN",
    "HAS_ORIGINAL_DD1348",
    "AVAILABLE_PDF_OK",
    "AVAILABLE_PDF_OPENED_NO_TEXT",
}


@dataclass
class ScanResult:
    identifier: str
    status: str
    detail: str
    details_url: str = ""
    has_original_dd1348: str = ""  # yes | no | unknown
    ui_label: str = ""  # "Click to Open" | "Unavailable" | ...


def _csv_safe(value: object) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").replace(",", " ")


def scan_one(
    list_page: Page,
    context: BrowserContext,
    identifier: str,
    efts_base: str,
    *,
    details_tab_timeout_ms: int = 300_000,
) -> tuple[ScanResult, Page]:
    """
    Click result (opens Details in a new tab) → wait until that tab is up and
    Document Center / Original DD1348 IRRD is populated → classify → close tab →
    return to List Search.
    """
    list_page = efts.return_to_list_search(context, list_page, efts_base)
    before = set(context.pages)
    same_tab = False
    details: Page | None = None

    try:
        details, same_tab, list_page = _open_details_tab(
            list_page,
            context,
            identifier,
            before,
            efts_base=efts_base,
            timeout_ms=details_tab_timeout_ms,
        )
        if details is None:
            list_page = efts.return_to_list_search(context, list_page, efts_base)
            return (
                ScanResult(
                    identifier,
                    "error",
                    "Details tab did not open",
                    "",
                    "unknown",
                    "",
                ),
                list_page,
            )

        # Continue work on the Details tab that just opened
        details.bring_to_front()
        try:
            details.wait_for_load_state("domcontentloaded", timeout=details_tab_timeout_ms)
        except Exception:
            pass

        if efts.is_efts_error_page(details):
            url = details.url or ""
            list_page = _finish_details(context, list_page, details, same_tab, efts_base)
            return (
                ScanResult(identifier, "error", "EFTS_ERROR_PAGE", url, "unknown", ""),
                list_page,
            )

        details_url = details.url or ""
        print(
            f"[scan] waiting for Details tab to populate "
            f"(up to {details_tab_timeout_ms // 1000}s) for {identifier}..."
        )
        # Wait until Document Center is up AND IRRD shows Click to Open / Unavailable
        irrd = efts.wait_for_irrd_ready(details, timeout_ms=details_tab_timeout_ms)
        ui_label = (irrd.get("label") or "").strip()
        detail = (irrd.get("detail") or "").strip()

        if str(detail).startswith("DETAILS_NOT_READY"):
            list_page = _finish_details(context, list_page, details, same_tab, efts_base)
            return (
                ScanResult(
                    identifier,
                    "error",
                    _csv_safe(detail),
                    details_url,
                    "unknown",
                    "",
                ),
                list_page,
            )

        if irrd["state"] == "unavailable":
            list_page = _finish_details(context, list_page, details, same_tab, efts_base)
            return (
                ScanResult(
                    identifier,
                    "UNAVAILABLE",
                    "Original DD1348 IRRD: Unavailable",
                    details_url,
                    "no",
                    "Unavailable",
                ),
                list_page,
            )

        if irrd["state"] == "available":
            list_page = _finish_details(context, list_page, details, same_tab, efts_base)
            return (
                ScanResult(
                    identifier,
                    "CLICK_TO_OPEN",
                    "Original DD1348 IRRD: Click to Open",
                    details_url,
                    "yes",
                    ui_label or "Click to Open",
                ),
                list_page,
            )

        list_page = _finish_details(context, list_page, details, same_tab, efts_base)
        return (
            ScanResult(
                identifier,
                "error",
                f"IRRD_UNCLEAR: {_csv_safe(detail or ui_label)}",
                details_url,
                "unknown",
                ui_label,
            ),
            list_page,
        )
    except Exception as exc:
        try:
            list_page = efts.return_to_list_search(context, list_page, efts_base)
        except Exception:
            pass
        return (
            ScanResult(identifier, "error", f"ERROR: {exc}", "", "unknown", ""),
            list_page,
        )


def _finish_details(
    context: BrowserContext,
    list_page: Page,
    details: Page,
    same_tab: bool,
    efts_base: str,
) -> Page:
    if same_tab:
        return efts.return_to_list_search(context, list_page, efts_base)
    try:
        if details != list_page and not details.is_closed():
            details.close()
    except Exception:
        pass
    return efts.return_to_list_search(context, list_page, efts_base)


def _open_details_tab(
    list_page: Page,
    context: BrowserContext,
    identifier: str,
    before: set[Page],
    *,
    efts_base: str,
    timeout_ms: int,
) -> tuple[Page | None, bool, Page]:
    """
    Click the List Search result and wait until a Details tab (or same-tab
    Details navigation) appears. Retries the click once if needed.
    Returns (details_page_or_none, same_tab, list_page).
    """
    import time

    end = time.time() + timeout_ms / 1000.0
    pages_before = set(before)
    clicked = False

    def _try_click() -> None:
        nonlocal clicked, pages_before, list_page
        list_page = efts.return_to_list_search(context, list_page, efts_base)
        pages_before = set(context.pages)
        efts.click_shipment_identifier(list_page, identifier)
        clicked = True

    _try_click()
    retried = False
    while time.time() < end:
        details = _wait_new_page(context, pages_before, timeout_ms=2_000)
        if details is not None:
            return details, False, list_page
        # Same-tab navigation fallback
        try:
            if efts.is_details_page(list_page):
                return list_page, True, list_page
        except Exception:
            pass
        # One retry click mid-wait (gov-cloud sometimes drops the first)
        remaining = end - time.time()
        if not retried and remaining > 15 and clicked:
            print(f"[scan] Details tab not yet open for {identifier}; retrying click...")
            try:
                _try_click()
                retried = True
            except Exception as exc:
                print(f"[scan] retry click failed: {exc}")
        time.sleep(0.25)
    return None, False, list_page


def _wait_new_page(
    context: BrowserContext, before: set[Page], timeout_ms: int
) -> Page | None:
    import time

    end = time.time() + timeout_ms / 1000.0
    while time.time() < end:
        for p in context.pages:
            if p not in before and not p.is_closed():
                try:
                    p.wait_for_load_state("domcontentloaded", timeout=60_000)
                except Exception:
                    pass
                return p
        time.sleep(0.25)
    return None


def run_baseline(
    *,
    list_page: Page,
    context: BrowserContext,
    efts_base: str,
    rows: list[ShipmentRow],
    search_by: str,
    out_dir: Path,
    throttle: Throttle,
    list_search_wait_seconds: int,
    label: str = "baseline",
    report_name: str | None = None,
    resume_from: str | None = None,
    midrun_cac_timeout_seconds: float = 300.0,
    details_tab_timeout_seconds: float = 300.0,
) -> dict:
    """
    Run (or resume) a baseline scan.

    Report folder: out_dir / <report_name>
    If report_name is empty, a timestamp folder is used.
    Resume loads prior CSV/state, skips completed IDs, and updates the same folder.
    """
    prior_rows: list[dict[str, str]] = []
    prior_ids: list[str] = []
    resumed = False

    if resume_from is not None:
        report_dir = find_resumable_report(out_dir, resume_from)
        state = load_state(report_dir) or {}
        report_name = report_dir.name
        label = str(state.get("label") or label)
        prior_ids = [str(x) for x in (state.get("planned_identifiers") or [])]
        prior_rows = load_result_rows(report_dir / "all-results.csv")
        if not prior_rows:
            # try stamped files
            stamped = sorted(report_dir.glob("all-results_*.csv"))
            if stamped:
                prior_rows = load_result_rows(stamped[-1])
        resumed = True
        print(f"[resume] Continuing report: {report_dir}")
    else:
        name = resolve_report_name(report_name)
        report_dir = resolve_report_dir(out_dir, name)
        report_name = report_dir.name

    report_dir.mkdir(parents=True, exist_ok=True)

    # Planned identifier list (full test scope)
    if resumed and prior_ids:
        planned = prior_ids
    else:
        planned = [r.identifier for r in rows]

    done = completed_identifiers(prior_rows)
    counts = recount_from_rows(prior_rows)
    remaining_rows = [
        r for r in rows if r.identifier.upper() not in done
    ]
    # If resume used stored planned list and current rows differ, prefer remaining from planned
    if resumed and prior_ids:
        remaining_ids = [i for i in planned if i.upper() not in done]
        by_id = {r.identifier.upper(): r for r in rows}
        remaining_rows = []
        for ident in remaining_ids:
            if ident.upper() in by_id:
                remaining_rows.append(by_id[ident.upper()])
            else:
                remaining_rows.append(
                    ShipmentRow(ident, None, "TCN", 0)
                )

    if resumed and not remaining_rows:
        print("[resume] Nothing left to scan — report already complete.")
        summary = _write_final_reports(
            report_dir=report_dir,
            label=label,
            report_name=report_name,
            search_by=search_by or "tcn",
            planned=planned,
            prior_rows=prior_rows,
            new_rows=[],
            expected=0,
            stopped_early=False,
            early_stop_reason="",
            resumed=True,
        )
        return summary

    ids = [r.identifier for r in remaining_rows]
    print(
        f"[report] name={report_name} dir={report_dir} "
        f"planned={len(planned)} already_done={len(done)} remaining={len(ids)}"
        + (" (resume)" if resumed else "")
    )

    upload = write_upload_txt(ids, report_dir / "list-search-upload.txt")
    working = input_dir() / "identifiers.txt"
    write_upload_txt(ids, working)

    efts.open_list_search(list_page, efts_base)
    efts.upload_or_paste_ids(list_page, upload, ids)
    efts.select_search_by(list_page, search_by or "tcn")
    efts.click_search(list_page)
    expected = efts.wait_for_results(list_page, list_search_wait_seconds)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # On resume, keep writing into the live "latest" files and a new stamp snapshot
    all_path = report_dir / f"all-results_{stamp}.csv"
    had_path = report_dir / f"had-dd1348_{stamp}.csv"
    no_path = report_dir / f"no-dd1348_{stamp}.csv"

    hit_count = counts["hits"]
    unavailable_count = counts["unavailable"]
    error_count = counts["errors"]
    scanned = counts["scanned"]
    found: set[str] = set(done)
    early_stop_reason = ""
    stopped_early = False
    new_result_rows: list[list[str]] = []

    header = [
        "identifier",
        "has_original_dd1348",
        "ui_label",
        "status",
        "detail",
        "detailsUrl",
    ]

    with (
        all_path.open("w", encoding="utf-8", newline="") as rf,
        had_path.open("w", encoding="utf-8", newline="") as hf,
        no_path.open("w", encoding="utf-8", newline="") as uf,
    ):
        results = csv.writer(rf)
        had = csv.writer(hf)
        no = csv.writer(uf)
        results.writerow(header)
        had.writerow(header)
        no.writerow(header)

        # Seed stamp files with prior completed rows so the snapshot is complete
        for prow in prior_rows:
            status = (prow.get("status") or "").strip()
            if status.upper() == "NOT_SCANNED_EARLY_STOP":
                continue
            csv_row = [
                prow.get("identifier", ""),
                prow.get("has_original_dd1348", ""),
                prow.get("ui_label", ""),
                prow.get("status", ""),
                prow.get("detail", ""),
                prow.get("detailsUrl", ""),
            ]
            results.writerow(csv_row)
            new_result_rows.append(csv_row)
            has = (prow.get("has_original_dd1348") or "").strip().lower()
            if has == "yes" or status in HIT_STATUSES:
                had.writerow(csv_row)
            elif has == "no" or status == "UNAVAILABLE":
                no.writerow(csv_row)

        page_num = 1
        more = True
        while more and not stopped_early:
            if not wait_out_midrun_cac(
                context, timeout_seconds=midrun_cac_timeout_seconds
            ):
                early_stop_reason = (
                    f"Mid-run CAC/login prompt did not clear within "
                    f"{int(midrun_cac_timeout_seconds)} seconds. "
                    "Partial results published."
                )
                stopped_early = True
                break

            try:
                list_page = efts.return_to_list_search(context, list_page, efts_base)
            except Exception as exc:
                if not wait_out_midrun_cac(
                    context, timeout_seconds=midrun_cac_timeout_seconds
                ):
                    early_stop_reason = (
                        f"Lost List Search during mid-run CAC challenge "
                        f"({exc}). Partial results published."
                    )
                    stopped_early = True
                    break
                list_page = efts.return_to_list_search(context, list_page, efts_base)

            page_ids = efts.collect_shipment_identifiers(list_page)
            print(f"[scan] page {page_num}: {len(page_ids)} shipment identifiers")
            for ident in page_ids:
                if stopped_early:
                    break
                key = ident.upper()
                if key in found:
                    continue
                found.add(key)
                try:
                    row, list_page = scan_one(
                        list_page,
                        context,
                        ident,
                        efts_base,
                        details_tab_timeout_ms=int(details_tab_timeout_seconds * 1000),
                    )
                except Exception as exc:
                    row = ScanResult(
                        ident, "error", f"ERROR: {exc}", "", "unknown", ""
                    )
                    try:
                        list_page = efts.return_to_list_search(
                            context, list_page, efts_base
                        )
                    except Exception:
                        if not wait_out_midrun_cac(
                            context, timeout_seconds=midrun_cac_timeout_seconds
                        ):
                            early_stop_reason = (
                                f"Mid-run CAC/login during scan of {ident}; "
                                f"did not clear within "
                                f"{int(midrun_cac_timeout_seconds)}s. "
                                "Partial results published."
                            )
                            stopped_early = True

                if not stopped_early and not wait_out_midrun_cac(
                    context, timeout_seconds=midrun_cac_timeout_seconds
                ):
                    early_stop_reason = (
                        f"Mid-run CAC/login after scanning {ident}; "
                        f"did not clear within "
                        f"{int(midrun_cac_timeout_seconds)}s. "
                        "Partial results published."
                    )
                    stopped_early = True

                scanned += 1
                csv_row = [
                    row.identifier,
                    row.has_original_dd1348,
                    _csv_safe(row.ui_label),
                    row.status,
                    _csv_safe(row.detail),
                    _csv_safe(row.details_url),
                ]
                results.writerow(csv_row)
                new_result_rows.append(csv_row)

                if row.has_original_dd1348 == "yes" or row.status in HIT_STATUSES:
                    hit_count += 1
                    had.writerow(csv_row)
                elif row.has_original_dd1348 == "no" or row.status == "UNAVAILABLE":
                    unavailable_count += 1
                    no.writerow(csv_row)
                else:
                    error_count += 1

                rf.flush()
                hf.flush()
                uf.flush()

                # Live update latest CSVs after each item (helps resume mid-crash)
                _write_live_csvs(report_dir, header, new_result_rows, planned, found, stopped_early=False)

                print(
                    f"[scan] {scanned}/{expected + counts['scanned']} {row.identifier} "
                    f"dd1348={row.has_original_dd1348} ui='{row.ui_label}' "
                    f"status={row.status} detail={_csv_safe(row.detail)[:120]}"
                )
                if stopped_early:
                    break
                throttle.after_item(scanned)

            if stopped_early:
                break
            if efts.has_next_page(list_page):
                more = efts.go_to_next_page(list_page)
                page_num += 1
            else:
                more = False

        not_found = 0
        if not stopped_early:
            for ident in planned:
                if ident.upper() not in found:
                    not_found += 1
                    csv_row = [ident, "unknown", "", "NOT_IN_LIST_SEARCH_RESULTS", "", ""]
                    results.writerow(csv_row)
                    new_result_rows.append(csv_row)
        else:
            for ident in planned:
                if ident.upper() not in found:
                    not_found += 1
                    csv_row = [ident, "unknown", "", "NOT_SCANNED_EARLY_STOP", "", ""]
                    results.writerow(csv_row)
                    new_result_rows.append(csv_row)

    latest_all = safe_copy(all_path, report_dir / "all-results.csv")
    latest_had = safe_copy(had_path, report_dir / "had-dd1348.csv")
    latest_no = safe_copy(no_path, report_dir / "no-dd1348.csv")

    save_state(
        report_dir,
        {
            "report_name": report_name,
            "label": label,
            "search_by": search_by or "tcn",
            "planned_identifiers": planned,
            "completed_identifiers": sorted(found),
            "stopped_early": stopped_early,
            "early_stop_reason": early_stop_reason,
            "resumed": resumed,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "scanned": scanned,
            "hits": hit_count,
            "unavailable": unavailable_count,
            "errors": error_count,
        },
    )

    summary_lines = [
        "DACS Original DD1348 IRRD report",
        f"report_name: {report_name}",
        f"label: {label}",
        f"resumed: {resumed}",
        f"search_by: {search_by or 'tcn'}",
        f"planned: {len(planned)}",
        f"uploaded_this_pass: {len(ids)}",
        f"list_search_results: {expected}",
        f"scanned: {scanned}",
        f"had_dd1348 (Click to Open): {hit_count}",
        f"no_dd1348 (Unavailable): {unavailable_count}",
        f"errors_or_unclear: {error_count}",
        f"not_in_results_or_remaining: {not_found}",
        f"hit_rate: {(hit_count / scanned) if scanned else 0.0:.1%}",
        f"stopped_early: {stopped_early}",
        f"early_stop_reason: {early_stop_reason or '(none)'}",
        "",
        f"report_dir: {report_dir}",
        f"had-dd1348: {latest_had}",
        f"no-dd1348:  {latest_no}",
        f"all-results: {latest_all}",
    ]
    if stopped_early:
        summary_lines.extend(
            [
                "",
                "To resume this test:",
                f"  python -m dacs_baseline scan --resume \"{report_name}\"",
                f"  or: python -m dacs_baseline scan --resume \"{report_dir}\"",
            ]
        )
    summary_text = "\n".join(summary_lines)
    summary_path = safe_write_text(report_dir / f"summary_{stamp}.txt", summary_text + "\n")
    latest_summary = safe_write_text(report_dir / "summary.txt", summary_text + "\n")
    print(summary_text)
    if early_stop_reason:
        print(f"[scan] EARLY STOP: {early_stop_reason}")
        print(f"[scan] Resume with: python -m dacs_baseline scan --resume \"{report_name}\"")

    return {
        "label": label,
        "report_name": report_name,
        "report_dir": str(report_dir),
        "resumed": resumed,
        "planned": len(planned),
        "uploaded": len(ids),
        "expected_results": expected,
        "scanned": scanned,
        "hits": hit_count,
        "unavailable": unavailable_count,
        "errors": error_count,
        "not_in_results": not_found,
        "hit_rate": (hit_count / scanned) if scanned else 0.0,
        "stopped_early": stopped_early,
        "early_stop_reason": early_stop_reason,
        "had_dd1348_file": str(latest_had),
        "no_dd1348_file": str(latest_no),
        "all_results_file": str(latest_all),
        "summary_file": str(latest_summary),
    }


def _write_live_csvs(
    report_dir: Path,
    header: list[str],
    result_rows: list[list[str]],
    planned: list[str],
    found: set[str],
    *,
    stopped_early: bool,
) -> None:
    """Best-effort live update of all-results.csv during a run."""
    try:
        path = report_dir / "all-results.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(result_rows)
            for ident in planned:
                if ident.upper() not in found:
                    status = (
                        "NOT_SCANNED_EARLY_STOP"
                        if stopped_early
                        else "IN_PROGRESS"
                    )
                    w.writerow([ident, "unknown", "", status, "", ""])
    except Exception:
        pass


def _write_final_reports(
    *,
    report_dir: Path,
    label: str,
    report_name: str,
    search_by: str,
    planned: list[str],
    prior_rows: list[dict[str, str]],
    new_rows: list[list[str]],
    expected: int,
    stopped_early: bool,
    early_stop_reason: str,
    resumed: bool,
) -> dict:
    counts = recount_from_rows(prior_rows)
    summary_lines = [
        "DACS Original DD1348 IRRD report",
        f"report_name: {report_name}",
        f"label: {label}",
        f"resumed: {resumed}",
        f"search_by: {search_by}",
        f"planned: {len(planned)}",
        f"scanned: {counts['scanned']}",
        f"had_dd1348 (Click to Open): {counts['hits']}",
        f"no_dd1348 (Unavailable): {counts['unavailable']}",
        f"errors_or_unclear: {counts['errors']}",
        f"stopped_early: {stopped_early}",
        f"early_stop_reason: {early_stop_reason or '(none)'}",
        f"report_dir: {report_dir}",
    ]
    summary_text = "\n".join(summary_lines)
    latest_summary = safe_write_text(report_dir / "summary.txt", summary_text + "\n")
    save_state(
        report_dir,
        {
            "report_name": report_name,
            "label": label,
            "planned_identifiers": planned,
            "stopped_early": False,
            "early_stop_reason": "",
            "resumed": resumed,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            **counts,
        },
    )
    print(summary_text)
    return {
        "label": label,
        "report_name": report_name,
        "report_dir": str(report_dir),
        "resumed": resumed,
        "planned": len(planned),
        "uploaded": 0,
        "expected_results": expected,
        "scanned": counts["scanned"],
        "hits": counts["hits"],
        "unavailable": counts["unavailable"],
        "errors": counts["errors"],
        "not_in_results": 0,
        "hit_rate": (counts["hits"] / counts["scanned"]) if counts["scanned"] else 0.0,
        "stopped_early": False,
        "early_stop_reason": "",
        "summary_file": str(latest_summary),
        "all_results_file": str(report_dir / "all-results.csv"),
        "had_dd1348_file": str(report_dir / "had-dd1348.csv"),
        "no_dd1348_file": str(report_dir / "no-dd1348.csv"),
    }
