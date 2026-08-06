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


HIT_STATUSES = {
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
    pdf_url: str = ""
    has_original_dd1348: str = ""  # yes | no | unknown


def _csv_safe(value: object) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").replace(",", " ")


def scan_one(
    list_page: Page,
    context: BrowserContext,
    identifier: str,
    efts_base: str,
) -> tuple[ScanResult, Page]:
    """
    Open TCN Details, check Original DD1348 IRRD (link vs Unavailable),
    write outcome, then always return to List Search results.
    """
    list_page = efts.return_to_list_search(context, list_page, efts_base)
    before = set(context.pages)
    same_tab = False
    details: Page | None = None

    try:
        efts.click_shipment_identifier(list_page, identifier)
        details = _wait_new_page(context, before, timeout_ms=15_000)
        if details is None:
            # Same-tab navigation fallback
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
                        "Details page did not open",
                        "",
                        "",
                        "unknown",
                    ),
                    list_page,
                )

        details.wait_for_load_state("domcontentloaded", timeout=300_000)
        details.wait_for_timeout(500)

        if efts.is_efts_error_page(details):
            url = details.url or ""
            list_page = _finish_details(context, list_page, details, same_tab, efts_base)
            return (
                ScanResult(identifier, "error", "EFTS_ERROR_PAGE", url, "", "unknown"),
                list_page,
            )

        details_url = details.url or ""
        irrd = efts.wait_for_irrd_ready(details, timeout_ms=90_000)

        if irrd["state"] == "unavailable":
            list_page = _finish_details(context, list_page, details, same_tab, efts_base)
            return (
                ScanResult(
                    identifier,
                    "UNAVAILABLE",
                    "Original DD1348 IRRD: Unavailable",
                    details_url,
                    "",
                    "no",
                ),
                list_page,
            )

        if irrd["state"] == "available":
            list_page = _finish_details(context, list_page, details, same_tab, efts_base)
            return (
                ScanResult(
                    identifier,
                    "HAS_ORIGINAL_DD1348",
                    f"Original DD1348 IRRD: link {_csv_safe(irrd.get('href') or irrd.get('detail'))}",
                    details_url,
                    irrd.get("href") or "",
                    "yes",
                ),
                list_page,
            )

        list_page = _finish_details(context, list_page, details, same_tab, efts_base)
        return (
            ScanResult(
                identifier,
                "error",
                f"IRRD_UNCLEAR: {_csv_safe(irrd.get('detail'))}",
                details_url,
                "",
                "unknown",
            ),
            list_page,
        )
    except Exception as exc:
        try:
            list_page = efts.return_to_list_search(context, list_page, efts_base)
        except Exception:
            pass
        return (
            ScanResult(identifier, "error", f"ERROR: {exc}", "", "", "unknown"),
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
        # details is list_page — go back to results
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
    out_dir.mkdir(parents=True, exist_ok=True)
    ids = [r.identifier for r in rows]
    upload = write_upload_txt(ids, input_dir() / "identifiers.txt")
    write_upload_txt(ids, out_dir / "list-search-upload.txt")

    efts.open_list_search(list_page, efts_base)
    efts.upload_or_paste_ids(list_page, upload, ids)
    efts.select_search_by(list_page, search_by or "requisition")
    efts.click_search(list_page)
    expected = efts.wait_for_results(list_page, list_search_wait_seconds)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_path = out_dir / f"dacs-dd1348-scan-results_{label}_{stamp}.csv"
    hits_path = out_dir / f"dacs-dd1348-baseline-hits_{label}_{stamp}.csv"
    unavail_path = out_dir / f"dacs-dd1348-unavailable_{label}_{stamp}.csv"

    hit_count = unavailable_count = error_count = scanned = 0
    found: set[str] = set()

    with (
        results_path.open("w", encoding="utf-8", newline="") as rf,
        hits_path.open("w", encoding="utf-8", newline="") as hf,
        unavail_path.open("w", encoding="utf-8", newline="") as uf,
    ):
        results = csv.writer(rf)
        hits = csv.writer(hf)
        unavail = csv.writer(uf)
        results.writerow(
            ["identifier", "has_original_dd1348", "status", "detail", "detailsUrl", "pdfUrl"]
        )
        hits.writerow(
            ["identifier", "has_original_dd1348", "status", "detail", "detailsUrl", "pdfUrl"]
        )
        unavail.writerow(
            ["identifier", "has_original_dd1348", "status", "detail", "detailsUrl"]
        )

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
                        ident, "error", f"ERROR: {exc}", "", "", "unknown"
                    )
                    list_page = efts.return_to_list_search(context, list_page, efts_base)

                scanned += 1
                results.writerow(
                    [
                        row.identifier,
                        row.has_original_dd1348,
                        row.status,
                        _csv_safe(row.detail),
                        _csv_safe(row.details_url),
                        _csv_safe(row.pdf_url),
                    ]
                )
                if row.status == "UNAVAILABLE" or row.has_original_dd1348 == "no":
                    unavailable_count += 1
                    unavail.writerow(
                        [
                            row.identifier,
                            row.has_original_dd1348 or "no",
                            "UNAVAILABLE",
                            _csv_safe(row.detail),
                            _csv_safe(row.details_url),
                        ]
                    )
                elif row.status in HIT_STATUSES or row.has_original_dd1348 == "yes":
                    hit_count += 1
                    hits.writerow(
                        [
                            row.identifier,
                            "yes",
                            row.status,
                            _csv_safe(row.detail),
                            _csv_safe(row.details_url),
                            _csv_safe(row.pdf_url),
                        ]
                    )
                if row.status == "error":
                    error_count += 1

                # Flush so a crash mid-run still leaves a usable report
                rf.flush()
                hf.flush()
                uf.flush()

                print(
                    f"[scan] {scanned}/{expected} {row.identifier} "
                    f"has_original_dd1348={row.has_original_dd1348} status={row.status}"
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
                    [ident, "unknown", "NOT_IN_LIST_SEARCH_RESULTS", "", "", ""]
                )

    latest_results = out_dir / f"dacs-dd1348-scan-results_{label}.csv"
    latest_hits = out_dir / f"dacs-dd1348-baseline-hits_{label}.csv"
    latest_unavail = out_dir / f"dacs-dd1348-unavailable_{label}.csv"
    shutil.copyfile(results_path, latest_results)
    shutil.copyfile(hits_path, latest_hits)
    shutil.copyfile(unavail_path, latest_unavail)

    summary = {
        "label": label,
        "uploaded": len(ids),
        "expected_results": expected,
        "scanned": scanned,
        "hits": hit_count,
        "unavailable": unavailable_count,
        "errors": error_count,
        "not_in_results": not_found,
        "hit_rate": (hit_count / scanned) if scanned else 0.0,
        "results_file": str(latest_results),
        "hits_file": str(latest_hits),
        "unavailable_file": str(latest_unavail),
    }
    print(
        f"[scan] complete label={label} uploaded={len(ids)} scanned={scanned} "
        f"has_dd1348={hit_count} unavailable={unavailable_count} errors={error_count} "
        f"hit_rate={summary['hit_rate']:.1%}"
    )
    return summary
