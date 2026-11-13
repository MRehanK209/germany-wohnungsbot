from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from . import contact, klein_login
from .browser import Browser
from .config import DATA_DIR, kleinanzeigen_credentials, load_config
from .dates import newest_first, parse_listing_date, utc_now
from .messages import build_contact_message
from .location import DEFAULT_CITY, LocationError, city_name, slugify
from .models import Listing
from .money import parse_euro_amount
from .scrapers import ALL_SCRAPERS
from .scrapers.base import parse_size_sqm
from .storage import Store
from .telegram import Telegram, platform_label

log = logging.getLogger("wohnungsbot")


def setup_logging():
    DATA_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(DATA_DIR / "bot.log", encoding="utf-8"),
        ],
    )


def passes_filters(cfg: dict, l: Listing, *, now: datetime | None = None,
                   check_rent: bool = True) -> bool:
    import re
    from .config import resolve_filters
    f = resolve_filters(cfg)

    # Age limit. Undated listings pass: some sites (e.g. Immowelt) never show a
    # date, and the bot only ever evaluates listings it has just discovered.
    max_age = f.get("max_listing_age_days")
    if max_age:
        published = parse_listing_date(l.published_at)
        checked_at = parse_listing_date(now) if now is not None else utc_now()
        if published is not None and not (checked_at - timedelta(days=max_age) <= published <= checked_at):
            return False

    # rooms
    if l.rooms is None:
        if not f.get("include_unknown_rooms", True):
            return False
    elif not (f["min_rooms"] <= l.rooms <= f["max_rooms"]):
        return False

    # Require a stated living area when either area limit is configured.
    min_size, max_size = f.get("min_size_sqm"), f.get("max_size_sqm")
    if min_size or max_size:
        size_sqm = parse_size_sqm(l.size)
        if size_sqm is None:
            return False
        if min_size and size_sqm < min_size:
            return False
        if max_size and size_sqm > max_size:
            return False

    # Rent ceiling: use the verified Warmmiete when the ad states one. Otherwise
    # fall back to the displayed price (may be Kaltmiete); the Telegram alert
    # then flags the warm rent as unconfirmed instead of silently dropping it.
    if check_rent and f.get("max_warm_rent_eur"):
        rent = parse_euro_amount(l.warm_rent_eur)
        if rent is None:
            rent = parse_euro_amount(l.price)
        if rent is None or rent <= 0 or rent > f["max_warm_rent_eur"]:
            return False

    # postal code(s) within the city — only if the user restricted to some.
    # Lenient: a listing whose address has no 5-digit PLZ is let through.
    codes = f.get("postal_codes") or []
    if codes:
        m = re.search(r"\b(\d{5})\b", l.address or "")
        if m and m.group(1) not in codes:
            return False

    return True


def try_contact(cfg, store: Store, browser, l: Listing) -> str | None:
    """Send the German viewing request. Returns a human-readable status."""
    handler = contact.HANDLERS.get(l.platform)
    if handler is None:
        return None
    if l.rooms is None:
        return "skipped (room count unknown — please check the ad yourself)"
    limit = cfg["contact"].get("max_per_hour", 8)
    if store.contacts_last_hour() >= limit:
        return f"skipped (limit of {limit}/hour reached — please contact manually)"
    message = build_contact_message(cfg, l)
    try:
        status = handler(browser, l, message)
        store.mark_contacted(l.platform, l.listing_id, status)
        return status
    except Exception as e:
        log.exception("Contact attempt failed: %s", l.url)
        return f"FAILED ({type(e).__name__}) — please contact manually"


def scan_platform(cfg, store, tg, browser, name, scraper_cls, allow_contact) -> bool:
    """Scan one platform; notify on new matches, optionally auto-contact them.

    Returns True if the fetch succeeded, False if it failed (e.g. rate-limited).
    """
    pconf = cfg["platforms"].get(name) or {}
    scraper = None
    fetched_ok = True
    try:
        scraper = scraper_cls(cfg)
        listings = newest_first(scraper.fetch(browser))
    except Exception as e:
        log.warning("Scraper %s failed: %s: %s", name, type(e).__name__, e)
        listings = []
        fetched_ok = False

    # First scan of a platform — or the first scan after switching city — is a
    # baseline: capped, no auto-contact, so the existing backlog doesn't flood Telegram.
    baselined = cfg.setdefault("_baselined", set())
    baseline = store.count(name) == 0 or (cfg.get("city_changed") and name not in baselined)
    fresh = [l for l in listings if not store.is_known(l.platform, l.listing_id)]
    pending = {listing.key: listing for listing in store.pending_notifications(name)}
    for listing in listings:
        cached = pending.get(listing.key)
        if cached is not None:
            if listing.published_at is None:
                listing.published_at = cached.published_at
            if listing.warm_rent_eur is None and listing.price == cached.price:
                listing.warm_rent_eur = cached.warm_rent_eur
            pending[listing.key] = listing
    candidates = newest_first([*fresh, *pending.values()])
    checked_at = utc_now()
    if fresh or baseline:
        log.info("%s: %d listings, %d new%s", name, len(listings), len(fresh),
                 " (baseline run, no auto-contact)" if baseline else "")

    first_run_cap = cfg.get("first_run_max_per_platform", 15)
    sent = 0
    for l in candidates:
        rent_lookup_failed = False
        if (cfg["filters"].get("max_warm_rent_eur") and l.warm_rent_eur is None
                and scraper is not None and not (baseline and sent >= first_run_cap)
                and passes_filters(cfg, l, now=checked_at, check_rent=False)):
            try:
                scraper.enrich_rent(l, browser)
            except Exception as exc:
                log.warning("Warm-rent lookup failed for %s: %s", l.url, type(exc).__name__)
                rent_lookup_failed = True
        store.add(l)
        if rent_lookup_failed:
            store.mark_notification_pending(l.platform, l.listing_id)
            continue
        if not passes_filters(cfg, l, now=checked_at):
            continue
        if baseline and sent >= first_run_cap:
            continue
        store.mark_notification_pending(l.platform, l.listing_id)
        status = None
        # Auto-contact ONLY genuinely new ads (never the baseline backlog),
        # and only where enabled + a browser session exists.
        if (allow_contact and not baseline and l.key not in pending and pconf.get("auto_contact")
                and browser is not None):
            status = try_contact(cfg, store, browser, l)
        try:
            tg.send_listing(l, status)
            store.mark_notified(l.platform, l.listing_id)
            sent += 1
            time.sleep(1.2)  # stay under Telegram's rate limit
        except Exception:
            log.exception("Telegram delivery failed for %s", l.url)

    if baseline and fetched_ok:
        baselined.add(name)
    if baseline:
        matched = sum(1 for l in fresh if passes_filters(cfg, l, now=checked_at))
        more = matched - sent
        if more > 0:
            _safe_tg(tg, f"ℹ️ {platform_label(name)}: showed {sent} of {matched} currently-listed "
                     f"matches (+{more} more already online). From now on you'll get each new one.")
    return fetched_ok


def rooms_label(cfg: dict) -> str:
    """Human label for the configured room count, e.g. '3 Zimmer', '3–3.5 Zimmer', '3+ Zimmer'."""
    f = cfg.get("filters") or {}
    lo, hi = f.get("min_rooms"), f.get("max_rooms")
    if lo is None:
        return "Wohnungen"
    if hi is None or hi >= 99:
        return f"{lo:g}+ Zimmer"
    if lo == hi:
        return f"{lo:g} Zimmer"
    return f"{lo:g}–{hi:g} Zimmer"


FAILURE_ALERT_AFTER = 3  # consecutive failed scans (= 15 min at the 5-min interval)


def track_platform_health(tg, name: str, ok: bool, fails: dict[str, int]):
    """Tell the user once when a platform keeps failing, and once when it recovers,
    so a broken scraper doesn't silently stop delivering ads."""
    previous = fails.get(name, 0)
    if ok:
        if previous >= FAILURE_ALERT_AFTER:
            _safe_tg(tg, f"✅ {platform_label(name)} is working again.")
        fails[name] = 0
        return
    fails[name] = previous + 1
    if fails[name] == FAILURE_ALERT_AFTER:
        hint = ("It is probably showing its 'Ich bin kein Roboter' captcha. Stop the bot, "
                "run ./login.sh immoscout24, solve it once, then start the bot again."
                if name == "immoscout24" else "Details are in data/bot.log.")
        _safe_tg(tg, f"⚠️ {platform_label(name)} has failed {FAILURE_ALERT_AFTER} scans in a row — "
                 f"no ads from it until this is fixed. {hint}")


def _safe_tg(tg, text):
    """Send a Telegram note but never let a network/Telegram error crash the loop."""
    try:
        tg.send(text)
    except Exception:
        log.warning("Telegram notify failed (continuing): %s", text[:50])


def remember_city(city: str) -> bool:
    """Record the searched city; True if it differs from the previous run's."""
    path = DATA_DIR / "city.txt"
    try:
        previous = path.read_text(encoding="utf-8").strip()
    except OSError:
        previous = ""
    try:
        path.write_text(city + "\n", encoding="utf-8")
    except OSError:
        log.warning("Could not save the city to %s", path)
    # No record yet = existing install that has only ever searched the default city.
    return slugify(previous or DEFAULT_CITY) != slugify(city)


def platform_active(cfg, name: str) -> bool:
    """Enabled in config.yaml and usable for the configured city (see prepare_platforms)."""
    if "active_platforms" in cfg:
        return name in cfg["active_platforms"]
    return bool((cfg["platforms"].get(name) or {}).get("enabled"))


def prepare_platforms(cfg, tg=None) -> list[str]:
    """Decide which enabled platforms can search the configured city.

    Local co-ops only serve their own city and are skipped elsewhere. Portals
    resolve the city to their own location id; if a portal doesn't know the
    city, it is skipped for this run and the user is told how to fix it.
    A network error during the lookup keeps the platform (it retries per scan).
    """
    city = city_name(cfg)
    active, skipped_local, problems = [], [], []
    for name, scraper_cls in ALL_SCRAPERS.items():
        if not (cfg["platforms"].get(name) or {}).get("enabled"):
            continue
        if not scraper_cls.serves_city(city):
            skipped_local.append(platform_label(name))
            continue
        try:
            scraper_cls(cfg).check_location()
        except LocationError as e:
            problems.append(f"• {platform_label(name)}: {e}")
            log.warning("%s skipped: %s", name, e)
            continue
        except Exception as e:
            log.warning("%s: location lookup failed (%s: %s) — will retry during scans",
                        name, type(e).__name__, e)
        active.append(name)
    cfg["active_platforms"] = active
    if skipped_local:
        log.info("Only for another city, skipped in %s: %s", city, ", ".join(skipped_local))
    if problems and tg is not None:
        _safe_tg(tg, f"⚠️ Some platforms can't search {city} and are skipped:\n" + "\n".join(problems))
    return active


def needs_browser(cfg) -> bool:
    for name, scraper_cls in ALL_SCRAPERS.items():
        pconf = cfg["platforms"].get(name) or {}
        if platform_active(cfg, name) and (scraper_cls.uses_browser or pconf.get("auto_contact")):
            return True
    return False


def run_loop(cfg, store, tg, browser):
    klein_interval = cfg.get("kleinanzeigen_interval_seconds", 30)
    others_interval = cfg.get("poll_interval_seconds", 300)
    klein_enabled = platform_active(cfg, "kleinanzeigen")

    # One-time login attempt so auto-contact has a session. Only when auto-contact
    # is on: the browser may be running just for ImmoScout24.
    klein_auto = (cfg["platforms"].get("kleinanzeigen") or {}).get("auto_contact")
    if browser is not None and klein_enabled and klein_auto:
        email, password = kleinanzeigen_credentials()
        ok, status = klein_login.attempt_login(browser, email, password)
        log.info("Kleinanzeigen login: %s", status)
        _safe_tg(tg, ("🔐 Kleinanzeigen logged in — auto-messaging is active."
                      if ok else f"⚠️ Kleinanzeigen not logged in: {status} "
                                 "New ads will still be sent to you as links until then."))

    # Adaptive back-off: if Kleinanzeigen starts rate-limiting the fast polling,
    # slow down (exponentially, capped) until it recovers, so we don't get the IP
    # blocked. base = configured interval; max_backoff caps the slow-down.
    max_backoff = max(120, klein_interval * 8)
    current = klein_interval
    fails = 0
    backoff_notified = False

    last_others = 0.0
    other_fails: dict[str, int] = {}
    while True:
        start = time.monotonic()

        if klein_enabled:
            ok = scan_platform(cfg, store, tg, browser, "kleinanzeigen",
                               ALL_SCRAPERS["kleinanzeigen"], allow_contact=True)
            if ok:
                if fails and backoff_notified:
                    _safe_tg(tg, f"✅ Kleinanzeigen recovered — back to a {klein_interval}s scan.")
                fails = 0
                current = klein_interval
                backoff_notified = False
            else:
                fails += 1
                current = min(klein_interval * (2 ** fails), max_backoff)
                log.warning("Kleinanzeigen scan failed (%dx) — backing off to %ss", fails, current)
                if fails >= 3 and not backoff_notified:
                    _safe_tg(tg, f"⚠️ Kleinanzeigen is rate-limiting the {klein_interval}s scan. "
                             f"Backing off to {current}s to protect the IP; I'll speed back up "
                             f"once it recovers. (Raise kleinanzeigen_interval_seconds if this persists.)")
                    backoff_notified = True

        if time.monotonic() - last_others >= others_interval:
            for name, scraper_cls in ALL_SCRAPERS.items():
                if name == "kleinanzeigen":
                    continue
                if not platform_active(cfg, name):
                    continue
                ok = scan_platform(cfg, store, tg, browser, name, scraper_cls, allow_contact=False)
                track_platform_health(tg, name, ok, other_fails)
            last_others = time.monotonic()

        time.sleep(max(1.0, current - (time.monotonic() - start)))


def main():
    setup_logging()
    cfg = load_config()
    store = Store()
    tg = Telegram()
    klein_interval = cfg.get("kleinanzeigen_interval_seconds", 30)
    others_interval = cfg.get("poll_interval_seconds", 300)
    label = rooms_label(cfg)
    city = city_name(cfg)
    cfg["city_changed"] = remember_city(city)
    active = prepare_platforms(cfg, tg)
    klein_auto = (cfg["platforms"].get("kleinanzeigen") or {}).get("auto_contact")
    klein_line = (f"• Kleinanzeigen: every {klein_interval}s + auto-message new matches"
                  if klein_auto else
                  f"• Kleinanzeigen: every {klein_interval}s (links only)")

    others = [platform_label(n) for n in active if n != "kleinanzeigen"]
    _safe_tg(tg, f"🤖 {city} apartment bot started — searching {label} in {city}.\n"
             + (f"{klein_line}\n" if "kleinanzeigen" in active else "")
             + f"• Every {others_interval // 60} min (links only): {', '.join(others) or 'none'}\n"
             + (f"• Listings up to {cfg['filters']['max_listing_age_days']} days old; newest first"
                if cfg["filters"].get("max_listing_age_days") else
                "• Newest listings first"))
    log.info("Started for %s. Kleinanzeigen %ss, others %ss. Platforms: %s",
             city, klein_interval, others_interval, ", ".join(active))

    try:
        if needs_browser(cfg):
            with Browser(headless=cfg.get("headless", True)) as browser:
                run_loop(cfg, store, tg, browser)
        else:
            run_loop(cfg, store, tg, None)
    except KeyboardInterrupt:
        log.info("Stopped.")
    except Exception:
        log.exception("Fatal error — exiting (launchd will restart).")
        raise


if __name__ == "__main__":
    main()
