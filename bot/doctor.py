"""Health check:  python -m bot.doctor

Verifies .env, Telegram, Playwright, and runs every enabled scraper once.
"""

from .browser import Browser
from .config import ROOT, env, load_config
from .location import city_name
from .main import needs_browser, passes_filters, platform_active, prepare_platforms
from .money import parse_euro_amount
from .scrapers import ALL_SCRAPERS


def check(label: str, ok: bool, extra: str = ""):
    print(f"  {'✓' if ok else '✗'} {label}" + (f" — {extra}" if extra else ""))
    return ok


def main():
    print("=== Apartment bot doctor ===\n")
    cfg = load_config()

    print("[1] Configuration")
    check(".env exists", (ROOT / ".env").exists(), "if not: python -m bot.wizard")
    for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FULL_NAME", "EMAIL", "PHONE"):
        check(var, bool(env(var)))

    print("\n[2] Telegram")
    try:
        from .telegram import Telegram
        Telegram().send("🩺 Doctor test: Telegram is working.")
        check("test message sent", True)
    except Exception as e:
        check("test message sent", False, str(e))

    print(f"\n[3] City: {city_name(cfg)}")
    prepare_platforms(cfg)
    for name in ALL_SCRAPERS:
        if (cfg["platforms"].get(name) or {}).get("enabled") and not platform_active(cfg, name):
            check(name, False, "can't search this city — skipped (see the warning above / data/bot.log)")

    print("\n[4] Browser")
    browser = None
    browser_ctx = None
    if not needs_browser(cfg):
        print("  - not needed (link-only mode, no login)")
    else:
        try:
            browser_ctx = Browser(headless=cfg.get("headless", True))
            browser = browser_ctx.__enter__()
            check(f"{browser.engine} starts", True)
        except Exception as e:
            check("browser starts", False, f"{e} — fix: playwright install chromium")

    print("\n[5] Scrapers (one trial run each)")
    for name, scraper_cls in ALL_SCRAPERS.items():
        if not platform_active(cfg, name):
            print(f"  - {name}: not used")
            continue
        try:
            scraper = scraper_cls(cfg)
            listings = scraper.fetch(browser)
            if cfg["filters"].get("max_warm_rent_eur"):
                for listing in listings:
                    if (listing.warm_rent_eur is None
                            and passes_filters(cfg, listing, check_rent=False)):
                        try:
                            scraper.enrich_rent(listing, browser)
                        except Exception:
                            pass
            matched = sum(passes_filters(cfg, listing) for listing in listings)
            undated = sum(listing.published_at is None for listing in listings)
            unpriced = sum(
                parse_euro_amount(listing.warm_rent_eur) in (None, 0) for listing in listings
            )
            check(name, True,
                  f"{len(listings)} listings found; {matched} match filters; "
                  f"{undated} undated; {unpriced} without a verified warm rent")
        except Exception as e:
            check(name, False, f"{type(e).__name__}: {e}")

    if browser_ctx is not None:
        browser_ctx.__exit__(None, None, None)

    print("\nDone. If everything is ✓: ./run.sh")


if __name__ == "__main__":
    main()
