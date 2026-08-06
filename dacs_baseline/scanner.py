from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from playwright.sync_api import BrowserContext, Page

from . import efts
from .spreadsheet import ShipmentRow, write_upload_txt
from .throttle import Throttle


@dataclass
class ScanResult:
    identifier: str
    status: str
    detail: str
    details_url: str = ""
    pdf_url: str = ""


def _csv_safe(value: object) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").replace(",", " ")


def scan_one(list_page: Page, context: BrowserContext, identifier: str) -> ScanResult:
    efts.close_extra_pages(context, list_page)
    before = set(context.pages)
    efts.click_shipment_identifier(list_page, identifier)
    details = _wait_new_page(context, before, timeout_ms=30_000)
    if details is None:
        return ScanResult(identifier, "error", "Details tab did not open", "", "")

    details.wait_for_load_state("domcontentloaded")
    details.wait_for_timeout(800)

    if efts.is_efts_error_page(details):
        url = details.url or ""
        efts.close_extra_pages(context, list_page)
        return ScanResult(identifier, "error", "EFTS_ERROR_PAGE", url, "")

    details_url = details.url or ""
    irrd = efts.inspect_original_dd1348_irrd(details)

    if irrd["state"] == "unavailable":
        efts.close_extra_pages(context, list_page)
        return ScanResult(identifier, "UNAVAILABLE", "UNAVAILABLE", details_url, "")

    if irrd["state"] != "available":
        efts.close_extra_pages(context, list_page)
        return ScanResult(
            identifier,
            "error",
            irrd.get("detail") or "IRRD_MISSING",
            details_url,
            "",
        )

    before_pdf = set(context.pages)
    efts.click_irrd_download(details)
    pdf_page = _wait_new_page(context, before_pdf, timeout_ms=20_000)
    if pdf_page is None:
        # sometimes PDF opens in same tab
        pdf_page = details

    pdf_page.wait_for_timeout(1500)
    pdf_url = pdf_page.url or ""
    text = ""
    try:
        text = pdf_page.locator("body").inner_text(timeout=3000) or ""
    except Exception:
        text = ""

    required = [identifier.rstrip("*"), "DD1348"]
    hay = text.upper()
    missing = [t for t in required if t.upper() not in hay]
    looks_pdf = (
        ".pdf" in pdf_url.lower()
        or "pdf" in pdf_url.lower()
        or "DD1348" in hay
        or "1348" in hay
    )

    if not missing and hay.strip():
        status = "AVAILABLE_PDF_OK"
        detail = f"PDF_OK preview={_csv_safe(text[:240])}"
    elif not text.strip() and looks_pdf:
        status = "AVAILABLE_PDF_OPENED_NO_TEXT"
        detail = f"PDF opened but text not readable url={pdf_url}"
    elif not missing:
        status = "AVAILABLE_PDF_OK"
        detail = "PDF_OK"
    else:
        # Link present + DACS returned something: still a hit for baseline purposes
        # unless clearly broken. Prefer OPENED_NO_TEXT when pdf-like.
        if looks_pdf:
            status = "AVAILABLE_PDF_OPENED_NO_TEXT"
            detail = f"PDF opened; missing tokens={('|'.join(missing))} url={pdf_url}"
        else:
            status = "AVAILABLE_PDF_FAIL"
            detail = f"PDF_FAIL missing={('|'.join(missing))} preview={_csv_safe(text[:240])}"

    efts.close_extra_pages(context, list_page)
    return ScanResult(identifier, status, detail, details_url, pdf_url)


def _wait_new_page(
    context: BrowserContext, before: set[Page], timeout_ms: int
) -> Page | None:
    import time

    end = time.time() + timeout_ms / 1000.0
    while time.time() < end:
        for p in context.pages:
            if p not in before and not p.is_closed():
                try:
                    p.wait_for_load_state("domcontentloaded", timeout=10_000)
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
    upload = write_upload_txt(ids, out_dir / "list-search-upload.txt")

    efts.open_list_search(list_page, efts_base)
    efts.upload_or_paste_ids(list_page, upload, ids)
    efts.select_search_by(list_page, search_by)
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
        results.writerow(["identifier", "status", "detail", "detailsUrl", "pdfUrl"])
        hits.writerow(["identifier", "pdfValidation", "detail", "detailsUrl", "pdfUrl"])
        unavail.writerow(["identifier", "status", "detail", "detailsUrl"])

        page_num = 1
        more = True
        while more:
            page_ids = efts.collect_shipment_identifiers(list_page)
            print(f"[scan] page {page_num}: {len(page_ids)} shipment identifiers")
            for ident in page_ids:
                key = ident.upper()
                if key in found:
                    continue
                found.add(key)
                try:
                    row = scan_one(list_page, context, ident)
                except Exception as exc:
                    row = ScanResult(ident, "error", f"ERROR: {exc}", "", "")
                    efts.close_extra_pages(context, list_page)

                scanned += 1
                results.writerow(
                    [
                        row.identifier,
                        row.status,
                        _csv_safe(row.detail),
                        _csv_safe(row.details_url),
                        _csv_safe(row.pdf_url),
                    ]
                )
                if row.status == "UNAVAILABLE":
                    unavailable_count += 1
                    unavail.writerow(
                        [row.identifier, "UNAVAILABLE", _csv_safe(row.detail), _csv_safe(row.details_url)]
                    )
                elif row.status in {
                    "AVAILABLE_PDF_OK",
                    "AVAILABLE_PDF_OPENED_NO_TEXT",
                }:
                    hit_count += 1
                    hits.writerow(
                        [
                            row.identifier,
                            row.status,
                            _csv_safe(row.detail),
                            _csv_safe(row.details_url),
                            _csv_safe(row.pdf_url),
                        ]
                    )
                if row.status in {"error", "AVAILABLE_PDF_FAIL"}:
                    error_count += 1

                if scanned % 25 == 0 or scanned == 1:
                    print(
                        f"[scan] progress scanned={scanned}/{expected} "
                        f"hits={hit_count} unavailable={unavailable_count} errors={error_count}"
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
                results.writerow([ident, "NOT_IN_LIST_SEARCH_RESULTS", "", "", ""])

    # latest copies for easy compare
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
        f"hits={hit_count} unavailable={unavailable_count} errors={error_count} "
        f"hit_rate={summary['hit_rate']:.1%}"
    )
    return summary
