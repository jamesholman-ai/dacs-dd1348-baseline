from __future__ import annotations

import time
from typing import Iterable

from playwright.sync_api import BrowserContext, Page


def page_looks_like_cac_or_login(page: Page) -> bool:
    """True when the browser is on a CAC / login / welcome gate (not EFTS app)."""
    try:
        if page.is_closed():
            return False
        url = (page.url or "").lower()
        if any(
            x in url
            for x in (
                "/welcome",
                "login",
                "signin",
                "smartcard",
                "cac",
                "pkinit",
                "certpick",
            )
        ):
            # NewEftsWeb Details/ListSearch should not match
            if "neweftsweb" in url and "welcome" not in url:
                return False
            return True
        try:
            body = (page.locator("body").inner_text(timeout=1500) or "").upper()
        except Exception:
            body = ""
        cues = (
            "SMARTCARD",
            "SMART CARD",
            "CAC LOGIN",
            "CLIENT CERTIFICATE",
            "SELECT A CERTIFICATE",
            "PIN",
            "YOU ARE ACCESSING A U.S. GOVERNMENT",
        )
        efts_cues = ("DOCUMENT CENTER", "LIST SEARCH", "TCN DETAILS", "RESULTS (")
        if any(c in body for c in efts_cues):
            return False
        return any(c in body for c in cues)
    except Exception:
        return False


def context_has_cac_challenge(context: BrowserContext) -> bool:
    for p in list(context.pages):
        if page_looks_like_cac_or_login(p):
            return True
    return False


def wait_out_midrun_cac(
    context: BrowserContext,
    *,
    timeout_seconds: float = 300.0,
) -> bool:
    """
    If a mid-run CAC/login challenge appears, wait up to timeout_seconds.
    Returns True if cleared, False if still present after timeout.
    """
    if not context_has_cac_challenge(context):
        return True
    print(
        f"[cac] Mid-run CAC/login detected — waiting up to "
        f"{int(timeout_seconds)}s for it to clear..."
    )
    end = time.time() + timeout_seconds
    while time.time() < end:
        if not context_has_cac_challenge(context):
            print("[cac] Mid-run CAC/login cleared — continuing.")
            return True
        time.sleep(2)
    print("[cac] Mid-run CAC/login still present after timeout — stopping run.")
    return False


def any_page_urls(context: BrowserContext) -> list[str]:
    out: list[str] = []
    for p in context.pages:
        try:
            out.append(p.url or "")
        except Exception:
            pass
    return out
