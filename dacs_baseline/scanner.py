from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from playwright.sync_api import BrowserContext, Page

from . import efts
from .input_path import input_dir
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
) -> tuple[ScanResult, Page]:
    """
    Click result (opens Details in a new tab) → stay on that tab →
    read Original DD1348 IRRD (Click to Open vs Unavailable) → close tab →
    return to List Search.
    """
    list_page = efts.return_to_list_search(context, list_page, efts_base)
    before = set(context.pages)
    same_tab = False
    details: Page | None = None

    try:
        efts.click_shipment_identifier(list_page, identifier)
        details = _wait_new_page(context, before, timeout_ms=30_000)
        if details is None:
            list_page.wait_for_timeout(1000)
            if efts.is_details_page(list_page):
                details = list_page
                same_tab = True
            else:
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
            details.wait_for_load_state("domcontentloaded", timeout=300_000)
        except Exception:
            pass
        details.wait_for_timeout(800)

        if efts.is_efts_error_page(details):
            url = details.url or ""
            list_page = _finish_details(context, list_page, details, same_tab, efts_base)
            return (
                ScanResult(identifier, "error", "EFTS_ERROR_PAGE", url, "unknown", ""),
                list_page,
            )

        details_url = details.url or ""
        try:
            efts.ensure_details_ready(details, timeout_ms=90_000)
        except Exception as exc:
            list_page = _finish_details(context, list_page, details, same_tab, efts_base)
            return (
                ScanResult(
                    identifier,
                    "error",
                    f"DETAILS_NOT_READY: {_csv_safe(exc)}",
                    details_url,
                    "unknown",
                    "",
                ),
                list_page,
            )

        irrd = efts.wait_for_irrd_ready(details, timeout_ms=60_000)
        ui_label = (irrd.get("label") or "").strip()
        detail = (irrd.get("detail") or "").strip()

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


def _wait_new_page(
    context: BrowserContext, before: set[Page], timeout_ms: int
) -> Page | None:
    import time

    end = time.time() + timeout_ms / 1000.0
    while time.time() < end:
        for p in context.pages:
            if p not in before and not p.is_closed():
                try:
                    p.wait_for_load_state("domcontentloaded", timeout=300_000)
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
) -> dict:
    # reports/dd1348-irrd/<label>/
    report_dir = out_dir / label if out_dir.name != label else out_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    ids = [r.identifier for r in rows]
    # Upload copy for this run only — do not overwrite identifiers-full-462.txt
    upload = write_upload_txt(ids, report_dir / "list-search-upload.txt")
    working = input_dir() / "identifiers.txt"
    write_upload_txt(ids, working)

    efts.open_list_search(list_page, efts_base)
    efts.upload_or_paste_ids(list_page, upload, ids)
    efts.select_search_by(list_page, search_by or "tcn")
    efts.click_search(list_page)
    expected = efts.wait_for_results(list_page, list_search_wait_seconds)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    all_path = report_dir / f"all-results_{stamp}.csv"
    had_path = report_dir / f"had-dd1348_{stamp}.csv"
    no_path = report_dir / f"no-dd1348_{stamp}.csv"
    summary_path = report_dir / f"summary_{stamp}.txt"

    hit_count = unavailable_count = error_count = scanned = 0
    found: set[str] = set()

    with (
        all_path.open("w", encoding="utf-8", newline="") as rf,
        had_path.open("w", encoding="utf-8", newline="") as hf,
        no_path.open("w", encoding="utf-8", newline="") as uf,
    ):
        results = csv.writer(rf)
        had = csv.writer(hf)
        no = csv.writer(uf)
        header = [
            "identifier",
            "has_original_dd1348",
            "ui_label",
            "status",
            "detail",
            "detailsUrl",
        ]
        results.writerow(header)
        had.writerow(header)
        no.writerow(header)

        page_num = 1
        more = True
        while more:
            list_page = efts.return_to_list_search(context, list_page, efts_base)
            page_ids = efts.collect_shipment_identifiers(list_page)
            print(f"[scan] page {page_num}: {len(page_ids)} shipment identifiers")
            for ident in page_ids:
                key = ident.upper()
                if key in found:
                    continue
                found.add(key)
                try:
                    row, list_page = scan_one(list_page, context, ident, efts_base)
                except Exception as exc:
                    row = ScanResult(
                        ident, "error", f"ERROR: {exc}", "", "unknown", ""
                    )
                    list_page = efts.return_to_list_search(context, list_page, efts_base)

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

                print(
                    f"[scan] {scanned}/{expected} {row.identifier} "
                    f"dd1348={row.has_original_dd1348} ui='{row.ui_label}' "
                    f"status={row.status} detail={_csv_safe(row.detail)[:120]}"
                )
                throttle.after_item(scanned)

            if efts.has_next_page(list_page):
                more = efts.go_to_next_page(list_page)
                page_num += 1
            else:
                more = False

        not_found = 0
        for ident in ids:
            if ident.upper() not in found:
                not_found += 1
                results.writerow(
                    [ident, "unknown", "", "NOT_IN_LIST_SEARCH_RESULTS", "", ""]
                )

    # Stable "latest" copies + human summary
    latest_all = report_dir / "all-results.csv"
    latest_had = report_dir / "had-dd1348.csv"
    latest_no = report_dir / "no-dd1348.csv"
    latest_summary = report_dir / "summary.txt"
    shutil.copyfile(all_path, latest_all)
    shutil.copyfile(had_path, latest_had)
    shutil.copyfile(no_path, latest_no)

    summary_text = "\n".join(
        [
            "DACS Original DD1348 IRRD report",
            f"label: {label}",
            f"search_by: {search_by or 'tcn'}",
            f"uploaded: {len(ids)}",
            f"list_search_results: {expected}",
            f"scanned: {scanned}",
            f"had_dd1348 (Click to Open): {hit_count}",
            f"no_dd1348 (Unavailable): {unavailable_count}",
            f"errors_or_unclear: {error_count}",
            f"not_in_results: {not_found}",
            f"hit_rate: {(hit_count / scanned) if scanned else 0.0:.1%}",
            "",
            f"had-dd1348: {latest_had}",
            f"no-dd1348:  {latest_no}",
            f"all-results: {latest_all}",
        ]
    )
    summary_path.write_text(summary_text + "\n", encoding="utf-8")
    latest_summary.write_text(summary_text + "\n", encoding="utf-8")
    print(summary_text)

    return {
        "label": label,
        "report_dir": str(report_dir),
        "uploaded": len(ids),
        "expected_results": expected,
        "scanned": scanned,
        "hits": hit_count,
        "unavailable": unavailable_count,
        "errors": error_count,
        "not_in_results": not_found,
        "hit_rate": (hit_count / scanned) if scanned else 0.0,
        "had_dd1348_file": str(latest_had),
        "no_dd1348_file": str(latest_no),
        "all_results_file": str(latest_all),
        "summary_file": str(latest_summary),
    }
