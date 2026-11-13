"""Interactive setup:  python -m bot.wizard

Asks for the Telegram token and your personal data, auto-detects your
chat id, sends a test message, and writes the .env file.
"""

from __future__ import annotations

import time

import httpx

from .config import (
    ROOT, load_config, parse_max_age_spec, parse_rent_limit_spec,
    parse_size_limit_spec, parse_rooms_spec,
)
from .location import city_name, is_default_city


def detect_chat_id(token: str) -> str | None:
    print("\nNow open Telegram and send your bot any message (e.g. 'hello').")
    print("Waiting... (up to 60 seconds)")
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            r = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15)
            for upd in reversed(r.json().get("result", [])):
                msg = upd.get("message") or upd.get("channel_post")
                if msg and msg.get("chat"):
                    return str(msg["chat"]["id"])
        except Exception:
            pass
        time.sleep(2)
    return None


def ask(label: str, example: str = "") -> str:
    hint = f" (e.g. {example})" if example else ""
    return input(f"{label}{hint}: ").strip()


def main():
    filters = load_config()["filters"]
    lo, hi = filters["min_rooms"], filters["max_rooms"]
    default_rooms = (f"{lo:g}+" if hi >= 99 else
                     f"{lo:g}" if lo == hi else f"{lo:g}-{hi:g}")
    default_min_size = f"{filters.get('min_size_sqm') or 0:g}"
    default_max_size = f"{filters.get('max_size_sqm') or 0:g}"
    default_max_age = str(filters.get("max_listing_age_days", 7) or 0)
    default_max_rent = f"{filters.get('max_warm_rent_eur') or 0:g}"
    default_city = city_name(load_config())
    print("=== Apartment bot — setup ===\n")
    print("Step 1: Create a bot on Telegram with @BotFather (/newbot)")
    token = ask("Bot token from @BotFather")
    if not token:
        raise SystemExit("Cannot continue without a token. Aborting.")

    chat_id = detect_chat_id(token)
    if chat_id:
        print(f"✓ Chat id found: {chat_id}")
    else:
        chat_id = ask("Could not detect the chat id automatically. Please enter it manually")

    print("\nStep 2: What to search for.")
    city = ask(f"City (blank = {default_city})", "Berlin, München, Hamburg") or default_city
    print("Rooms (Zimmer, German counting — the living room counts). Examples:")
    print("  1 = studio / one-room apartment     1-2 = 1 to 2 rooms     3+ = 3 or more")
    while True:
        rooms = ask(f"Rooms (blank = {default_rooms})") or default_rooms
        try:
            lo, hi = parse_rooms_spec(rooms)
            if not (0 < lo <= hi <= 99):
                raise ValueError
            break
        except ValueError:
            print("Please enter a room count or range, e.g. 1, 1-2 or 3+.")
    while True:
        size_spec = ask(f"Minimum area in m² (blank = {default_min_size}, 0 = any)") or default_min_size
        try:
            min_size = parse_size_limit_spec(size_spec)
            break
        except ValueError as exc:
            print(exc)
    while True:
        size_spec = ask(f"Maximum area in m² (blank = {default_max_size}, 0 = any)") or default_max_size
        try:
            max_size = parse_size_limit_spec(size_spec)
            if min_size and max_size and min_size > max_size:
                raise ValueError("Minimum area cannot exceed maximum area.")
            break
        except ValueError as exc:
            print(exc)
    while True:
        age_spec = ask(f"Maximum listing age in days (blank = {default_max_age}, 0 = any)") or default_max_age
        try:
            max_age = parse_max_age_spec(age_spec)
            break
        except ValueError as exc:
            print(exc)
    print("\nWarmmiete ceiling: rent including operating and heating charges.")
    print("Listings without a verified warm-rent amount are skipped when capped.")
    while True:
        rent_spec = ask(f"Maximum monthly Warmmiete in € (blank = {default_max_rent}, 0 = any)") or default_max_rent
        try:
            max_rent = parse_rent_limit_spec(rent_spec)
            break
        except ValueError as exc:
            print(exc)
    print(f"\nPostal codes to limit the search to (within {city}). Comma-separated.")
    if is_default_city(city):
        print("  Göttingen PLZ: 37073 37075 37077 37079 37081 37083 37085")
    print(f"  Leave blank to search ALL of {city}.")
    postal = ask("Postal codes (blank = all)", "")

    print("\nStep 3: Your details — used to fill the name/email/phone fields on contact forms.")
    full_name = ask("Full name")
    email = ask("Email")
    phone = ask("Phone number", "+49 151 2345678")
    occupation = ask("Occupation (German)", "Software Engineer mit unbefristetem Vertrag")
    household = ask("One sentence about your household (optional, German)", "")

    env_path = ROOT / ".env"
    env_path.write_text(
        f"TELEGRAM_BOT_TOKEN={token}\n"
        f"TELEGRAM_CHAT_ID={chat_id}\n"
        f"SEARCH_CITY={city}\n"
        f"SEARCH_ROOMS={rooms}\n"
        f"SEARCH_MIN_SIZE_SQM={min_size:g}\n"
        f"SEARCH_MAX_SIZE_SQM={max_size:g}\n"
        f"SEARCH_MAX_AGE_DAYS={max_age}\n"
        f"SEARCH_MAX_WARM_RENT_EUR={max_rent:g}\n"
        f"SEARCH_POSTAL_CODES={postal}\n"
        f"FULL_NAME={full_name}\n"
        f"EMAIL={email}\n"
        f"PHONE={phone}\n"
        f"OCCUPATION={occupation}\n"
        f"HOUSEHOLD={household}\n",
        encoding="utf-8",
    )
    where = postal.strip() or f"all of {city}"
    print(f"\n✓ Saved: {env_path}")
    print(f"  Searching {lo:g}–{hi:g} Zimmer in {where}.")
    if min_size and max_size:
        print(f"  Living area: {min_size:g}–{max_size:g} m².")
    elif min_size:
        print(f"  At least {min_size:g} m².")
    elif max_size:
        print(f"  Up to {max_size:g} m².")
    if min_size or max_size:
        print("  Listings with unknown area are skipped.")
    if max_age:
        print(f"  Listings no more than {max_age} days old; unknown publication dates are skipped.")
    if max_rent:
        print(f"  Warmmiete up to {max_rent:g} €; unknown warm rents are skipped.")
    print("  Newest listings are checked and sent first within each platform.")

    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id,
                  "text": f"✅ Setup complete! The {city} apartment bot is ready to start."},
            timeout=15,
        ).raise_for_status()
        print("✓ Test message sent to Telegram — check your chat.")
    except Exception as e:
        print(f"! Test message failed: {e}")

    print("\nNext steps:")
    print("  1. python -m bot.doctor   (test everything)")
    print("  2. ./run.sh               (start the bot)")
    print("  No platform login is needed for the default link-only configuration.")


if __name__ == "__main__":
    main()
