from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import BrowserContext, Page


IRRD_ID = "originalDD1348irrd"
DEFAULT_NAV_TIMEOUT_MS = 300_000  # 5 minutes — gov-cloud lag


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
            page.wait_for_load_state("domcontentloaded", timeout=DEFAULT_NAV_TIMEOUT_MS)
            dismiss_scip_modals(page)
            return
    except Exception:
        pass
    base = efts_base if efts_base.endswith("/") else efts_base + "/"
    page.goto(
        base + "ListSearch",
        wait_until="domcontentloaded",
        timeout=DEFAULT_NAV_TIMEOUT_MS,
    )
    dismiss_scip_modals(page)


def select_search_by(page: Page, mode: str) -> None:
    """
    Select List Search 'Search By' radio.

    Locators from EFTS Katalon / efts-element-map.json (list search page):
      - container: #searchBy
      - tcn: #radio_TCN
      - requisition: #radio_REQ
      - labels: All | TCN | Requisition | Contract
    """
    mode = (mode or "tcn").strip().lower()
    # Prefer stable EFTS element ids first
    id_map = {
        "tcn": ["radio_TCN"],
        "requisition": ["radio_REQ", "radio_REQN", "radio_Requisition"],
        "document": ["radio_REQ", "radio_DOC", "radio_Document"],
        "all": ["radio_ALL", "radio_0"],
        "contract": ["radio_CTN", "radio_CONTRACT", "radio_Contract"],
    }
    for rid in id_map.get(mode, []):
        try:
            loc = page.locator(f"#{rid}").first
            if loc.count():
                loc.click(force=True)
                print(f"[list-search] Search By = {mode} (#{rid})")
                return
        except Exception:
            continue

    label_text = {
        "tcn": "TCN",
        "requisition": "Requisition",
        "document": "Requisition",
        "all": "All",
        "contract": "Contract",
    }.get(mode, "TCN")

    selectors = [
        f"#searchBy label:text-is('{label_text}')",
        f"#searchBy label:has-text('{label_text}')",
        f"#searchBy input[type='radio'][value='{label_text}' i]",
        f"#searchBy input[type='radio'][id*='{label_text}' i]",
        f"label:text-is('{label_text}')",
        f"label:has-text('{label_text}')",
        f"input[type='radio'][value='{label_text}' i]",
        f"input[type='radio'][id*='{label_text}' i]",
    ]
    if mode == "tcn":
        selectors[0:0] = [
            "#searchBy input[type='radio'][value='TCN' i]",
            "input[type='radio'][value='TCN' i]",
            "#radio_TCN",
        ]

    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=1000):
                loc.click()
                print(f"[list-search] Search By = {label_text} ({sel})")
                return
        except Exception:
            continue
    print(f"[list-search] WARNING: could not find Search By={mode}; leaving default")


def upload_or_paste_ids(page: Page, upload_txt: Path, ids: list[str]) -> None:
    """
    Prefer file upload via #fileInput (efts-element-map list search).
    Fallback: paste into #docIds textarea.
    """
    # Ensure upload file exists (one ID per line)
    upload_txt = Path(upload_txt)
    if not upload_txt.exists():
        upload_txt.parent.mkdir(parents=True, exist_ok=True)
        upload_txt.write_text("\n".join(ids) + "\n", encoding="utf-8")

    file_input = page.locator("#fileInput, input[type='file']")
    try:
        if file_input.count() == 0:
            # Reveal via "choose from folder" / #fileSelectButton
            for sel in ("#fileSelectButton", "a:has-text('choose from folder')", "text=choose from folder"):
                try:
                    btn = page.locator(sel).first
                    if btn.count() and btn.is_visible(timeout=800):
                        btn.click()
                        break
                except Exception:
                    continue
            page.wait_for_timeout(500)
        if file_input.count():
            file_input.first.set_input_files(str(upload_txt.resolve()))
            page.wait_for_timeout(800)
            print(f"[list-search] uploaded {upload_txt} via file input")
            return
    except Exception as exc:
        print(f"[list-search] upload failed ({exc}); pasting into #docIds")

    area = page.locator(
        "#docIds, textarea, "
        "[placeholder*='Document' i], [placeholder*='TCN' i]"
    ).first
    area.wait_for(state="visible", timeout=15_000)
    area.fill("\n".join(ids))
    print(f"[list-search] pasted {len(ids)} ids into document textarea")


def click_search(page: Page) -> None:
    btn = page.locator(
        "#submitCriteriaBtn, button:text-is('Search'), "
        "input[type='submit'][value*='Search' i], "
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
    """Click result row; force target=_blank so List Search stays open."""
    page.locator("#resultsTable").wait_for(state="attached", timeout=30_000)
    result = page.evaluate(
        """(id) => {
        const table = document.getElementById('resultsTable');
        if (!table) return 'NO_TABLE';
        const anchors = table.querySelectorAll('a[href*="Details"]');
        for (const a of anchors) {
          const text = (a.innerText || a.textContent || '').trim();
          if (text === id) {
            a.setAttribute('target', '_blank');
            a.setAttribute('rel', 'noopener noreferrer');
            a.scrollIntoView({block: 'center', inline: 'nearest'});
            a.click();
            return 'CLICKED';
          }
        }
        // Prefix match (list may show shorter form than Details title)
        const upper = id.toUpperCase();
        for (const a of anchors) {
          const text = (a.innerText || a.textContent || '').trim().toUpperCase();
          if (text.startsWith(upper) || upper.startsWith(text)) {
            a.setAttribute('target', '_blank');
            a.setAttribute('rel', 'noopener noreferrer');
            a.scrollIntoView({block: 'center', inline: 'nearest'});
            a.click();
            return 'CLICKED_PREFIX';
          }
        }
        return 'NOT_FOUND';
    }""",
        identifier,
    )
    if not str(result).startswith("CLICKED"):
        link = page.locator(
            f"#resultsTable a[href*='Details']:text-is('{identifier}')"
        ).first
        if link.count() == 0:
            raise RuntimeError(f"Shipment Identifier link not found: {identifier}")
        page.evaluate(
            """(el) => { el.setAttribute('target','_blank'); el.click(); }""",
            link.element_handle(),
        )


def is_list_search_results(page: Page) -> bool:
    try:
        if page.is_closed():
            return False
        url = (page.url or "").lower()
        if "listsearch" in url and page.locator("#resultsTable").count() > 0:
            return True
        return page.locator("#resultsTable a[href*='Details']").count() > 0
    except Exception:
        return False


def is_details_page(page: Page) -> bool:
    try:
        url = (page.url or "").lower()
        return "details" in url and "listsearch" not in url
    except Exception:
        return False


def ensure_details_ready(page: Page, timeout_ms: int = 300_000) -> None:
    """
    Wait until the Details tab is up and Document Center / Original DD1348
    content is present (not just a blank shell).
    """
    import time

    end = time.time() + timeout_ms / 1000.0
    last_err = ""
    while time.time() < end:
        try:
            if page.is_closed():
                raise RuntimeError("Details tab closed unexpectedly")
            dismiss_scip_modals(page)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5_000)
            except Exception:
                pass
            url = (page.url or "").lower()
            body = ""
            try:
                body = page.locator("body").inner_text(timeout=2000) or ""
            except Exception as exc:
                last_err = str(exc)
                page.wait_for_timeout(500)
                continue
            upper = body.upper()
            # Require real Details content — not an empty shell.
            has_doc_center = "DOCUMENT CENTER" in upper
            has_irrd_heading = "ORIGINAL DD1348" in upper
            has_tcn_details = "TCN DETAILS" in upper or (
                "DETAILS" in upper and "SHIPMENT" in upper
            )
            ready = (has_doc_center and has_irrd_heading) or (
                has_irrd_heading and ("CLICK TO OPEN" in upper or "UNAVAILABLE" in upper)
            ) or (has_doc_center and has_tcn_details and len(body) > 400)

            if ready:
                try:
                    page.evaluate(
                        """() => {
                        const nodes = Array.from(document.querySelectorAll('*'));
                        const hit = nodes.find(n => {
                          const t = (n.innerText || '').trim();
                          return /^Document Center$/i.test(t)
                              || /Original DD1348 IRRD/i.test(t);
                        });
                        if (hit) hit.scrollIntoView({block: 'center'});
                    }"""
                    )
                except Exception:
                    pass
                page.wait_for_timeout(500)
                return
            last_err = (
                f"url={url[:80]} body_len={len(body)} "
                f"doc_center={has_doc_center} irrd={has_irrd_heading}"
            )
        except Exception as exc:
            last_err = str(exc)
        page.wait_for_timeout(750)
    raise TimeoutError(
        f"Details page did not populate Document Center / Original DD1348 within "
        f"{timeout_ms // 1000}s ({last_err})"
    )


def wait_for_irrd_ready(page: Page, timeout_ms: int = 300_000) -> dict:
    """Wait until Original DD1348 IRRD shows 'Click to Open' or 'Unavailable'."""
    import time

    started = time.time()
    try:
        ensure_details_ready(page, timeout_ms=timeout_ms)
    except Exception as exc:
        return {
            "state": "missing",
            "detail": f"DETAILS_NOT_READY: {exc}",
            "href": "",
            "label": "",
        }

    remaining_ms = max(30_000, int(timeout_ms - (time.time() - started) * 1000))
    # Cap remaining so total stay near the requested timeout
    remaining_ms = min(remaining_ms, timeout_ms)
    end = time.time() + remaining_ms / 1000.0
    last = {"state": "missing", "detail": "IRRD_TIMEOUT", "href": "", "label": ""}
    while time.time() < end:
        last = inspect_original_dd1348_irrd(page)
        if last["state"] in {"unavailable", "available"}:
            return last
        page.wait_for_timeout(750)
    return last


def inspect_original_dd1348_irrd(page: Page) -> dict:
    """
    On the open Details tab, find Original DD1348 IRRD and classify:
      - available  → "Click to Open"
      - unavailable → "Unavailable"
    Uses #originalDD1348irrd when present, else parses Document Center text
    so Carrier Proof of Delivery's Unavailable is not confused with DD1348.
    """
    # Fast path: Playwright text locators on this tab
    try:
        # Scope under Document Center when possible
        doc = page.locator(
            "text=Document Center"
        ).first
        scope = page
        if doc.count():
            # Prefer a nearby panel ancestor
            try:
                panel = doc.locator(
                    "xpath=ancestor::*[contains(@class,'card') or contains(@class,'panel') "
                    "or contains(@class,'document') or contains(@class,'col')][1]"
                )
                if panel.count():
                    scope = panel
            except Exception:
                pass

        # Exact UI strings from Document Center screenshots
        if scope.locator("text=Click to Open").count() or page.locator(
            "a:has-text('Click to Open'), text=Click to Open"
        ).count():
            # Prefer Click to Open that sits under Original DD1348 IRRD
            parsed = _parse_irrd_from_dom(page)
            if parsed["state"] != "missing":
                return parsed
            href = ""
            try:
                link = page.locator("a:has-text('Click to Open')").first
                if link.count():
                    href = (link.get_attribute("href") or "").strip()
            except Exception:
                pass
            return {
                "state": "available",
                "detail": "Click to Open",
                "href": href,
                "label": "Click to Open",
            }
    except Exception:
        pass

    return _parse_irrd_from_dom(page)


def _parse_irrd_from_dom(page: Page) -> dict:
    """JS parse of Original DD1348 IRRD block on the current Details tab."""
    try:
        result = page.evaluate(
            """() => {
            function clean(s) {
              return (s || '').replace(/\\s+/g, ' ').trim();
            }
            const byId = document.getElementById('originalDD1348irrd')
              || document.querySelector('[id*="originaldd1348" i]')
              || document.querySelector('[id*="originalDD1348"]');

            let chunk = '';
            let href = '';

            if (byId) {
              chunk = clean(byId.innerText || byId.textContent || '');
              const a = byId.querySelector('a');
              if (a) href = (a.getAttribute('href') || '').trim();
            }

            // Parse body text between Original DD1348 IRRD and the next Document Center item
            const body = clean(document.body ? document.body.innerText : '');
            const re = /Original\\s*DD1348\\s*IRRD\\s*:?\\s*([\\s\\S]{0,200}?)(?=Carrier\\s+Proof|Create\\s+a\\s+duplicate|Attachments|Current Snapshot|$)/i;
            const m = body.match(re);
            if (m && m[1]) {
              chunk = clean(m[1]);
            }

            // Also look for an anchor whose nearby text mentions Original DD1348
            if (!href) {
              const anchors = Array.from(document.querySelectorAll('a'));
              for (const a of anchors) {
                const t = clean(a.innerText || a.textContent || '');
                if (/click\\s*to\\s*open/i.test(t)) {
                  // Ensure this is in the DD1348 area, not some other open link
                  const parentText = clean((a.closest('div,li,section,td') || a.parentElement || a).innerText || '');
                  if (/DD1348|IRRD/i.test(parentText) || /Original/i.test(parentText) || true) {
                    // Prefer first Click to Open that appears after Original DD1348 in body order
                    href = (a.getAttribute('href') || '').trim();
                    if (!/click\\s*to\\s*open/i.test(chunk)) {
                      chunk = (chunk + ' ' + t).trim();
                    }
                    break;
                  }
                }
              }
            }

            const upper = (chunk || '').toUpperCase();
            if (upper.includes('CLICK TO OPEN') || (/CLICK\\s*TO\\s*OPEN/i.test(body) && /ORIGINAL\\s*DD1348\\s*IRRD/i.test(body))) {
              // Confirm Click to Open is associated with Original DD1348, not only elsewhere
              const assoc = /Original\\s*DD1348\\s*IRRD[\\s\\S]{0,120}Click\\s*to\\s*Open/i.test(body)
                || upper.includes('CLICK TO OPEN');
              if (assoc) {
                return { state: 'available', detail: 'Click to Open', href: href || '', label: 'Click to Open', chunk };
              }
            }
            if (/Original\\s*DD1348\\s*IRRD[\\s\\S]{0,120}Unavailable/i.test(body) || upper.includes('UNAVAILABLE')) {
              // Only if Unavailable follows Original DD1348 before next section
              const unavailAssoc = /Original\\s*DD1348\\s*IRRD[\\s\\S]{0,120}Unavailable/i.test(body)
                || (upper.includes('UNAVAILABLE') && !upper.includes('CLICK TO OPEN'));
              if (unavailAssoc) {
                return { state: 'unavailable', detail: 'Unavailable', href: '', label: 'Unavailable', chunk };
              }
            }

            return {
              state: 'missing',
              detail: chunk ? ('IRRD_CHUNK:' + chunk.slice(0, 160)) : 'IRRD_NOT_FOUND_ON_PAGE',
              href: '',
              label: '',
              chunk: chunk || body.slice(0, 240)
            };
        }"""
        )
        if not isinstance(result, dict):
            return {
                "state": "missing",
                "detail": "IRRD_EVAL_BAD_RESULT",
                "href": "",
                "label": "",
            }
        return {
            "state": result.get("state") or "missing",
            "detail": result.get("detail") or "",
            "href": result.get("href") or "",
            "label": result.get("label") or "",
        }
    except Exception as exc:
        return {
            "state": "missing",
            "detail": f"IRRD_EVAL_ERROR: {exc}",
            "href": "",
            "label": "",
        }


def click_irrd_download(page: Page) -> None:
    container = page.locator(f"#{IRRD_ID}").first
    if container.count() == 0:
        container = page.locator("[id*='originaldd1348' i]").first
    link = container.locator("a[href]:not([href='']):not([href='#'])").first
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


def return_to_list_search(
    context: BrowserContext,
    list_page: Page,
    efts_base: str,
) -> Page:
    """
    Always get back to List Search results after a Details check.
    Handles Details opened in a new tab OR same-tab navigation.
    """
    # Close Details / PDF tabs; keep the list page handle if possible
    for p in list(context.pages):
        if p.is_closed():
            continue
        if p == list_page:
            continue
        try:
            if is_details_page(p) or "pdf" in (p.url or "").lower():
                p.close()
            elif not is_list_search_results(p):
                p.close()
        except Exception:
            try:
                p.close()
            except Exception:
                pass

    # Revive list_page if it was closed
    if list_page.is_closed():
        for p in context.pages:
            if is_list_search_results(p):
                p.bring_to_front()
                return p
        # Last resort: reopen List Search (results will need re-query by caller)
        page = context.pages[0] if context.pages else context.new_page()
        open_list_search(page, efts_base)
        return page

    # Same-tab case: navigated to Details on list_page
    if is_details_page(list_page) or not is_list_search_results(list_page):
        try:
            list_page.go_back(wait_until="domcontentloaded", timeout=DEFAULT_NAV_TIMEOUT_MS)
            list_page.wait_for_timeout(800)
        except Exception:
            pass
        if not is_list_search_results(list_page):
            try:
                list_page.go_back(wait_until="domcontentloaded", timeout=DEFAULT_NAV_TIMEOUT_MS)
                list_page.wait_for_timeout(800)
            except Exception:
                pass
        if not is_list_search_results(list_page):
            open_list_search(list_page, efts_base)

    try:
        list_page.bring_to_front()
    except Exception:
        pass
    return list_page


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
