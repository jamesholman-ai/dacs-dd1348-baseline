from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import BrowserContext, Page


IRRD_ID = "originalDD1348irrd"


def dismiss_scip_modals(page: Page) -> None:
    for sel in (
        "#closeButton",
        "input[value='Complete Later']",
        "button:has-text('Complete Later')",
        "button:has-text('OK')",
        "button:has-text('I Agree')",
        "button:has-text('Agree')",
    ):
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=500):
                loc.click(timeout=2000)
        except Exception:
            pass


def click_cac_if_present(page: Page) -> bool:
    """Click CAC / Smartcard login affordance if on SCIP portal."""
    candidates = [
        "a:has-text('CAC')",
        "a:has-text('Smartcard')",
        "a:has-text('Smart Card')",
        "button:has-text('CAC')",
        "a[href*='cac' i]",
        "a[href*='smartcard' i]",
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=800):
                loc.click(timeout=5000)
                return True
        except Exception:
            continue
    return False


def wait_for_efts_ready(page: Page, timeout_ms: int = 600_000) -> None:
    """
    Block until CAC/login completes and EFTS UI is usable.
    Operator completes PIN / cert picker in the Chrome dialog.
    """
    import time

    end = time.time() + (timeout_ms / 1000.0)
    print("[cac] Waiting for EFTS after CAC login (complete PIN/cert prompt in Chrome)...")
    while time.time() < end:
        dismiss_scip_modals(page)
        click_cac_if_present(page)
        url = (page.url or "").lower()
        try:
            body = page.locator("body").inner_text(timeout=1000)
        except Exception:
            body = ""
        upper = body.upper()
        ready_signals = (
            "LIST SEARCH" in upper
            or "ADVANCED SEARCH" in upper
            or "NEW EFTS" in upper
            or (
                "EFTS" in upper
                and ("RESEARCH" in upper or "MENU" in upper or "SEARCH" in upper)
            )
            or "resultsTable" in page.content()
            or page.locator("#research2, a[href*='ListSearch']").count() > 0
        )
        loginish = any(
            x in upper
            for x in ("CAC", "SMARTCARD", "SMART CARD", "SIGN IN", "LOG IN", "CERTIFICATE")
        )
        if ready_signals and not ("welcome" in url and loginish and "neweftsweb" not in url):
            # Prefer NewEftsWeb path or List Search visible
            if "neweftsweb" in url or page.locator("a[href*='ListSearch'], #research2").count() > 0:
                print(f"[cac] EFTS ready: {page.url}")
                dismiss_scip_modals(page)
                return
            if "listsearch" in url:
                print(f"[cac] EFTS List Search ready: {page.url}")
                return
        time.sleep(2)
    raise TimeoutError("Timed out waiting for CAC login / EFTS readiness")


def open_list_search(page: Page, efts_base: str) -> None:
    dismiss_scip_modals(page)
    link = page.locator(
        "a#research2, a[href*='ListSearch']:has-text('List Search'), "
        "a[href*='ListSearch'], a:text-is('List Search')"
    ).first
    try:
        if link.count() and link.is_visible(timeout=3000):
            link.click()
            page.wait_for_load_state("domcontentloaded")
            dismiss_scip_modals(page)
            return
    except Exception:
        pass
    base = efts_base if efts_base.endswith("/") else efts_base + "/"
    page.goto(base + "ListSearch", wait_until="domcontentloaded")
    dismiss_scip_modals(page)


def select_search_by(page: Page, mode: str) -> None:
    """Select List Search radio: tcn | document | requisition."""
    labels = {
        "tcn": ["TCN"],
        "document": ["Document", "Document Number", "Document Numbers", "Doc"],
        "requisition": ["Requisition", "REQ", "RQSTN"],
    }
    for label in labels.get(mode, ["TCN"]):
        for sel in (
            f"label:text-is('{label}')",
            f"label:has-text('{label}')",
            f"input[type='radio'][value='{label}' i]",
            f"input[type='radio'][id*='{label}' i]",
        ):
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible(timeout=1000):
                    loc.click()
                    print(f"[list-search] Search By = {label}")
                    return
            except Exception:
                continue
    print(f"[list-search] WARNING: could not find Search By={mode}; leaving default")


def upload_or_paste_ids(page: Page, upload_txt: Path, ids: list[str]) -> None:
    file_input = page.locator("input[type='file']")
    try:
        if file_input.count() == 0:
            page.evaluate(
                """() => {
                const links = Array.from(document.querySelectorAll('a,button,span,label'));
                const choose = links.find(el => {
                  const t = (el.innerText || el.textContent || '').toLowerCase();
                  return t.includes('choose') || t.includes('upload') || t.includes('replace');
                });
                if (choose) choose.click();
            }"""
            )
            page.wait_for_timeout(500)
        if file_input.count():
            file_input.first.set_input_files(str(upload_txt.resolve()))
            page.wait_for_timeout(800)
            print(f"[list-search] uploaded {upload_txt}")
            return
    except Exception as exc:
        print(f"[list-search] upload failed ({exc}); pasting into textarea")

    area = page.locator(
        "textarea, "
        "[placeholder*='Document' i], [placeholder*='TCN' i]"
    ).first
    area.wait_for(state="visible", timeout=15_000)
    area.fill("\n".join(ids))


def click_search(page: Page) -> None:
    btn = page.locator(
        "button:text-is('Search'), input[type='submit'][value*='Search' i], "
        "a.btn:text-is('Search'), button.btn:text-is('Search')"
    ).first
    btn.click()
    print("[list-search] Search clicked")


def wait_for_results(page: Page, timeout_seconds: int = 900) -> int:
    import time

    end = time.time() + timeout_seconds
    while time.time() < end:
        count = read_results_count(page)
        links = count_details_links(page)
        if count is not None and count > 0 and links > 0:
            print(f"[list-search] Results ({count}), details links={links}")
            return count
        page.wait_for_timeout(5000)
    count = read_results_count(page)
    if count is None:
        raise TimeoutError(f"List Search results did not appear within {timeout_seconds}s")
    print(f"[list-search] Results ({count}) after wait")
    return count


def read_results_count(page: Page) -> int | None:
    try:
        text = page.locator("body").inner_text(timeout=2000)
        m = re.search(r"Results\s*\((\d+)\)", text)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def count_details_links(page: Page) -> int:
    try:
        return page.evaluate(
            """() => {
            const table = document.getElementById('resultsTable');
            if (!table) return 0;
            return table.querySelectorAll('a[href*="Details"]').length;
        }"""
        )
    except Exception:
        return 0


def collect_shipment_identifiers(page: Page) -> list[str]:
    page.locator("#resultsTable").wait_for(state="attached", timeout=60_000)
    _scroll_results(page)
    return page.evaluate(
        """() => {
        const out = [];
        const seen = {};
        const table = document.getElementById('resultsTable');
        if (!table) return out;
        for (const a of table.querySelectorAll('a[href*="Details"]')) {
          const text = (a.innerText || a.textContent || '').trim();
          if (!text || seen[text]) continue;
          seen[text] = true;
          out.push(text);
        }
        return out;
    }"""
    )


def click_shipment_identifier(page: Page, identifier: str) -> None:
    page.locator("#resultsTable").wait_for(state="attached", timeout=30_000)
    result = page.evaluate(
        """(id) => {
        const table = document.getElementById('resultsTable');
        if (!table) return 'NO_TABLE';
        for (const a of table.querySelectorAll('a[href*="Details"]')) {
          const text = (a.innerText || a.textContent || '').trim();
          if (text === id) {
            a.scrollIntoView({block: 'center', inline: 'nearest'});
            a.click();
            return 'CLICKED';
          }
        }
        return 'NOT_FOUND';
    }""",
        identifier,
    )
    if result != "CLICKED":
        link = page.locator(
            f"#resultsTable a[href*='Details']:text-is('{identifier}')"
        ).first
        if link.count() == 0:
            raise RuntimeError(f"Shipment Identifier link not found: {identifier}")
        link.click()


def has_next_page(page: Page) -> bool:
    return bool(
        page.evaluate(
            """() => {
        function findNext() {
          let n = document.querySelector('#resultsPagination a.pagination-link[aria-label="Next"]')
            || document.querySelector('ul.paginationServerSide a.pagination-link[aria-label="Next"]');
          if (n) return n;
          for (const a of document.querySelectorAll(
            '#resultsPagination a.pagination-link, ul.paginationServerSide a.pagination-link'
          )) {
            const t = (a.innerText || a.textContent || '').replace(/\\s+/g, ' ').trim();
            if (t === 'Next' || t.startsWith('Next')) return a;
          }
          return null;
        }
        const next = findNext();
        if (!next) return false;
        const li = next.closest('li');
        if (li && li.classList.contains('disabled')) return false;
        return true;
    }"""
        )
    )


def go_to_next_page(page: Page, timeout_seconds: int = 90) -> bool:
    if not has_next_page(page):
        return False
    first_before = page.evaluate(
        """() => {
        const a = document.querySelector('#resultsTable a[href*="Details"]');
        return a ? (a.innerText || a.textContent || '').trim() : '';
    }"""
    )
    clicked = page.evaluate(
        """() => {
        function findNext() {
          let n = document.querySelector('#resultsPagination a.pagination-link[aria-label="Next"]')
            || document.querySelector('ul.paginationServerSide a.pagination-link[aria-label="Next"]');
          if (n) return n;
          for (const a of document.querySelectorAll(
            '#resultsPagination a.pagination-link, ul.paginationServerSide a.pagination-link'
          )) {
            const t = (a.innerText || a.textContent || '').replace(/\\s+/g, ' ').trim();
            if (t === 'Next' || t.startsWith('Next')) return a;
          }
          return null;
        }
        const next = findNext();
        if (!next) return 'NO_NEXT';
        const li = next.closest('li');
        if (li && li.classList.contains('disabled')) return 'DISABLED';
        next.scrollIntoView({block: 'center'});
        next.click();
        return 'CLICKED';
    }"""
    )
    if clicked != "CLICKED":
        return False
    import time

    end = time.time() + timeout_seconds
    while time.time() < end:
        page.wait_for_timeout(1000)
        first_after = page.evaluate(
            """() => {
            const a = document.querySelector('#resultsTable a[href*="Details"]');
            return a ? (a.innerText || a.textContent || '').trim() : '';
        }"""
        )
        if count_details_links(page) > 0 and first_after and first_after != first_before:
            return True
    return count_details_links(page) > 0


def _scroll_results(page: Page) -> None:
    page.evaluate(
        """() => {
        const table = document.getElementById('resultsTable');
        let target = null;
        if (table) {
          let p = table.parentElement;
          while (p && p !== document.body) {
            const style = window.getComputedStyle(p);
            if ((p.scrollHeight > p.clientHeight + 20) &&
                (style.overflowY === 'auto' || style.overflowY === 'scroll' ||
                 style.overflow === 'auto' || style.overflow === 'scroll')) {
              target = p; break;
            }
            p = p.parentElement;
          }
        }
        target = target || document.scrollingElement || document.documentElement;
        let y = 0, guard = 0;
        const step = Math.max(200, Math.floor(target.clientHeight * 0.8) || 400);
        while (y < target.scrollHeight && guard < 120) {
          target.scrollTop = y; y += step; guard++;
        }
        if (table) table.scrollIntoView({block: 'start'});
    }"""
    )
    page.wait_for_timeout(400)


def is_efts_error_page(page: Page) -> bool:
    url = (page.url or "").lower()
    if "/error" in url or "error.aspx" in url:
        return True
    for sel in ("#exceptionRaisedError", "#errorMessage"):
        try:
            if page.locator(sel).count():
                return True
        except Exception:
            pass
    try:
        text = page.locator("body").inner_text(timeout=2000)
        return "EFTS has encountered an internal problem" in text
    except Exception:
        return False


def inspect_original_dd1348_irrd(page: Page) -> dict:
    """Mirror Katalon DacsDd1348BaselineWorkflow.inspectOriginalDd1348Irrd."""
    container = page.locator(f"#{IRRD_ID}").first
    if container.count() == 0:
        container = page.locator("[id*='originaldd1348' i], [id*='originalDD1348']").first
    if container.count() == 0:
        return {"state": "missing", "detail": "IRRD_CONTAINER_NOT_FOUND", "href": ""}

    try:
        panel_text = (container.inner_text(timeout=3000) or "").strip()
    except Exception:
        panel_text = ""
    upper = panel_text.upper()
    unavailable = "UNAVAILABLE" in upper
    try:
        if container.locator("img[src*='download_icon_disabled']").count():
            unavailable = True
    except Exception:
        pass

    link = container.locator("a").first
    has_link = False
    href = ""
    try:
        if link.count() and link.is_visible(timeout=1500):
            has_link = True
            href = (link.get_attribute("href") or "").strip()
    except Exception:
        pass

    if unavailable and not has_link:
        return {"state": "unavailable", "detail": "UNAVAILABLE", "href": ""}
    if has_link:
        return {"state": "available", "detail": href or panel_text, "href": href}
    if unavailable:
        return {"state": "unavailable", "detail": "UNAVAILABLE", "href": ""}
    return {"state": "missing", "detail": panel_text or "NO_LINK", "href": ""}


def click_irrd_download(page: Page) -> None:
    container = page.locator(f"#{IRRD_ID}").first
    if container.count() == 0:
        container = page.locator("[id*='originaldd1348' i]").first
    link = container.locator("a").first
    link.click()


def close_extra_pages(context: BrowserContext, keep: Page) -> None:
    for p in list(context.pages):
        if p != keep and not p.is_closed():
            try:
                p.close()
            except Exception:
                pass
    try:
        keep.bring_to_front()
    except Exception:
        pass
