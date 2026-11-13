"""Kleinanzeigen login helpers (Auth0 flow at login.kleinanzeigen.de).

Reality check: the login page shows a "Bestätigen Sie, dass Sie ein Mensch
sind" bot-check that a script cannot solve. So the model is:
  - establish the session ONCE via `python -m bot.login` (a human solves the
    captcha; credentials are pre-filled from .env), then
  - the persistent browser profile reuses that session for all later runs.
attempt_login() tries a fully-automatic login for the lucky case where no
captcha is shown; if the captcha appears it gives up immediately (never
hammers the account) and tells you to run bot.login once.
"""

from __future__ import annotations

import logging

log = logging.getLogger("wohnungsbot")

LOGIN_URL = "https://www.kleinanzeigen.de/m-einloggen.html"
ACCOUNT_URL = "https://www.kleinanzeigen.de/m-meins.html"

COOKIE_BUTTONS = [
    "#gdpr-banner-accept",
    "button:has-text('Alle akzeptieren')",
    "button:has-text('Akzeptieren')",
    "button:has-text('Zustimmen')",
]
CAPTCHA_MARKERS = ["Mensch", "kein Roboter", "hCaptcha", "captcha"]


def _accept_cookies(page):
    for sel in COOKIE_BUTTONS:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=3000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def _captcha_present(page) -> bool:
    try:
        body = page.inner_text("body")
    except Exception:
        body = ""
    return any(m.lower() in body.lower() for m in CAPTCHA_MARKERS)


def is_logged_in(browser) -> bool:
    """True if the persistent session can reach the account page without a login redirect."""
    page = browser.page()
    try:
        page.goto(ACCOUNT_URL, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(1500)
        url = page.url.lower()
        return "login" not in url and "einloggen" not in url
    except Exception:
        return False
    finally:
        page.close()


def fill_credentials(page, email: str | None, password: str | None):
    """Best-effort fill of whatever email/password fields are on the current page."""
    if email:
        for sel in ["input#username", "input[name='username']",
                    "input[type='email']", "input[name*='mail' i]"]:
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible():
                    loc.fill(email)
                    break
            except Exception:
                continue
    if password:
        for sel in ["input#password", "input[name='password']", "input[type='password']"]:
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible():
                    loc.fill(password)
                    break
            except Exception:
                continue


def attempt_login(browser, email: str | None, password: str | None) -> tuple[bool, str]:
    """Try a fully-automatic login. Returns (logged_in, human_readable_status)."""
    if not email or not password:
        return False, "no credentials in .env (run `python -m bot.credentials`)"
    if is_logged_in(browser):
        return True, "already logged in (reused saved session)"

    page = browser.page()
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        _accept_cookies(page)
        page.wait_for_timeout(1500)
        fill_credentials(page, email, None)  # identifier-first: email, then continue

        if _captcha_present(page):
            return False, ("captcha shown — cannot auto-solve. Run `python -m bot.login` "
                           "once (a human solves the checkbox; the session is then saved).")

        # Auth0 identifier step -> continue
        for sel in ["button:has-text('Weiter')", "button:has-text('Continue')",
                    "button[type='submit']"]:
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible():
                    loc.click(timeout=5000)
                    break
            except Exception:
                continue
        page.wait_for_timeout(2500)

        if _captcha_present(page):
            return False, ("captcha shown after email — cannot auto-solve. "
                           "Run `python -m bot.login` once.")

        fill_credentials(page, None, password)
        for sel in ["button:has-text('Anmelden')", "button:has-text('Einloggen')",
                    "button[type='submit']"]:
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible():
                    loc.click(timeout=5000)
                    break
            except Exception:
                continue
        page.wait_for_timeout(3500)
    except Exception as e:
        return False, f"auto-login error ({type(e).__name__}) — run `python -m bot.login`"
    finally:
        page.close()

    if is_logged_in(browser):
        return True, "auto-login succeeded"
    return False, "auto-login did not complete — run `python -m bot.login` once"
