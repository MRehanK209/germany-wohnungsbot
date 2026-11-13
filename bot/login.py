"""Establish the Kleinanzeigen session ONCE, by hand:

    python -m bot.login

Opens a real Chrome window, warms up on the homepage, pre-fills your email +
password from .env, and lets YOU solve the "Bestätigen Sie, dass Sie ein
Mensch sind" checkbox and finish logging in. The session is saved in
data/browser-profile and reused by the bot (also headless) for auto-messaging.
Re-run whenever the session expires.

ImmoScout24 shows an "Ich bin kein Roboter" captcha to automated browsers:

    python -m bot.login immoscout24

opens the Göttingen search in the same Chrome profile so YOU can solve it once;
the bot then reuses that cookie. Re-run when the bot reports ImmoScout24 failing.

(The other platforms are notify-only and need no login.)
"""

import sys


from .browser import Browser
from .config import kleinanzeigen_credentials, load_config
from .klein_login import _accept_cookies, fill_credentials, is_logged_in

HOME = "https://www.kleinanzeigen.de/"
LOGIN = "https://www.kleinanzeigen.de/m-einloggen.html"


def immoscout_main():
    from .scrapers.immoscout24 import ImmoScout24

    url = ImmoScout24(load_config()).search_url()
    print("A Chrome window will open on the ImmoScout24 search.")
    print("  1. If 'Ich bin kein Roboter' appears, solve it (and accept cookies).")
    print("  2. Wait until the apartment list is visible, then come back here and press Enter.\n")
    with Browser(headless=False) as browser:
        page = browser.page()
        try:
            page.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            print(f"  ! Could not open the page ({e}). Navigate to {url} in the window.")
        input("When you see the apartment list: press Enter to save and close... ")
        try:
            ok = page.query_selector('a[href*="/expose/"]') is not None
        except Exception:
            ok = False
    print("✓ ImmoScout24 unlocked — the bot will reuse this session." if ok
          else "⚠️ No listings were visible. If the bot keeps reporting ImmoScout24 failing, run this again.")


def main():
    if any(arg.lower() in ("immoscout24", "immoscout", "is24") for arg in sys.argv[1:]):
        immoscout_main()
        return
    email, password = kleinanzeigen_credentials()
    if not email:
        print("No Kleinanzeigen credentials found. Run `python -m bot.credentials` first.")
        return

    print("A Chrome window will open. Steps:")
    print("  1. It warms up and pre-fills your email (and password when that field appears).")
    print("  2. YOU tick 'Bestätigen Sie, dass Sie ein Mensch sind' and click Weiter/Anmelden.")
    print("     Move the mouse to the checkbox slowly and pause before clicking.")
    print("  3. Finish any 2FA, then come back here and press Enter.\n")

    with Browser(headless=False) as browser:
        page = browser.page()
        try:
            page.goto(HOME, wait_until="domcontentloaded")
            _accept_cookies(page)
            page.wait_for_timeout(1500)
            page.goto(LOGIN, wait_until="domcontentloaded")
            _accept_cookies(page)
            page.wait_for_timeout(1500)
            fill_credentials(page, email, password)
            print("  → Login page open, email pre-filled. Solve the checkbox and log in.")
        except Exception as e:
            print(f"  ! Could not open the login page ({e}). Navigate to {LOGIN} in the window.")
        input("\nWhen you are logged in: press Enter to save the session and close... ")
        ok = is_logged_in(browser)
    print("✓ Session saved — you are logged in." if ok
          else "⚠️ Could not confirm login. If the bot reports 'not logged in', run this again.")


if __name__ == "__main__":
    main()
