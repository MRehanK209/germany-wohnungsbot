# 🏠 Germany Wohnungsbot

A bot that scans the major German rental platforms for apartments in **any German city**
matching **the room count, area range and postal code you choose at setup**, and pings you on
Telegram when it discovers a new matching listing. Set `SEARCH_CITY` in `.env`;
the default city is Göttingen. Platform availability varies by city (see below).

Repository: [MRehanK209/germany-wohnungsbot](https://github.com/MRehanK209/germany-wohnungsbot).
Existing installations can keep their current folder name and macOS autostart setup.

The current defaults search for **studios and 1–2-room apartments from
28–50 m²** across Göttingen, with a **600 € Warmmiete ceiling**. Listings outside that area range
or without a stated living area are skipped. Room count and area do not establish whether
a landlord accepts two occupants; check the individual listing.

Listings must have a site-reported publication date within the **last 7 days**.
Future publication dates are skipped; undated listings can still alert when first discovered.
Dates without a time are treated
as midnight in Europe/Berlin; the age limit is a rolling 7 × 24 hours.
The bot requests newest-first ordering on Kleinanzeigen, WG-Gesucht and ImmoScout24,
and sorts dated results newest first within each platform before sending alerts.
The age of undated listings cannot be verified. The time the bot first saw an ad
does not establish its age.

Set `SEARCH_MAX_WARM_RENT_EUR` in `.env` to cap monthly Warmmiete across all
enabled platforms, for example `SEARCH_MAX_WARM_RENT_EUR=600`. `0` means no cap.
The limit includes the exact amount. The bot checks explicit Warmmiete fields
or complete operating/heating charges, fetching detail pages for new candidates
when needed. A displayed Kaltmiete or a Gesamtmiete without confirmed heating
costs does not confirm Warmmiete. If warm rent is unknown, the bot applies the cap
to the advertised price and flags the unconfirmed warm rent in Telegram, so the actual
Warmmiete may exceed your ceiling. Temporary lookup failures are retried.
Both `600.50` and `600,50` are accepted. Warmmiete does not normally
include separate household electricity or internet bills.

Telegram delivery state is cached in `data/listings.db` by platform and listing
ID. Confirmed deliveries are not sent again after a restart. Failed sends stay
pending and retry on later scans while they still match your filters, including
when the listing has left the first search page. Existing seen IDs are preserved
when upgrading. Telegram and SQLite cannot share one transaction: a crash or
timeout after Telegram accepts a message but before local confirmation can cause
a retry of that message.

- **Kleinanzeigen** — scanned every few seconds (links only by default; optional
  auto-message to new matches with a one-time login).
- **All other platforms** — scanned every 5 minutes, links only (no login).

> **Room counting (German).** The living room counts as a room, so a 2-bedroom +
> living room + kitchen + bathroom flat is a **3-Zimmer-Wohnung**. At setup you pick
> whatever you want — `3` (exactly 3), `3-3.5` (a range), `2-4`, or `3+` — and that
> drives both the searches and the alerts.

> ⚠️ **Account risk.** Scanning Kleinanzeigen every 30s *and* auto-messaging is
> aggressive — it's the behaviour most likely to get the account flagged/banned by
> their bot-detection. Dial `kleinanzeigen_interval_seconds` up to 60–90 in
> [config.yaml](config.yaml) if you want to play it safer. A per-hour message cap
> (`contact.max_per_hour`) is on by default as a brake.

## Platforms covered

| Platform | Status | Notes |
|---|---|---|
| Kleinanzeigen.de | ✅ 5s, links only | optional auto-message with login |
| Immowelt | ✅ 5 min, links only | big portal, lots of listings |
| WG-Gesucht | ✅ 5 min, links only | studios and whole-flat listings, according to your room range |
| Volksheimstätte eG | ✅ 5 min, links only | local co-op, first-come-first-served |
| Wohnungsgenossenschaft eG | ✅ 5 min, links only | local co-op |
| Vonovia | ✅ 5 min, links only | Germany's biggest landlord (rarely has Göttingen flats) |
| ImmobilienScout24 | ⏸️ off | biggest portal (also covers wohnungsboerse.net, which redirects to Scout); needs a visible Chrome window + a one-time captcha (see below) |
| Städtische Wohnungsbau (SWB) | ❌ n/a | no online listings — see below |

> **ImmoScout24 is off by default.** Its "Ich bin kein Roboter" wall blocks hidden
> browsers. To use it, set `immoscout24 enabled: true` **and** `headless: false` in
> [config.yaml](config.yaml) (a Chrome window then stays open while the bot runs), run
> `./login.sh immoscout24`, solve the captcha in the window that opens, wait for the
> apartment list, press Enter, then start the bot with `./run.sh`. Repeat the login step
> whenever Telegram says ImmoScout24 keeps failing.

> **Searching another city.** Set `SEARCH_CITY` in `.env` (default `Göttingen`), e.g.
> `SEARCH_CITY=Berlin` or `SEARCH_CITY=Frankfurt am Main`, then restart. Kleinanzeigen,
> WG-Gesucht, Immowelt and Vonovia look the city up automatically; the Göttingen-only
> co-ops (Volksheimstätte, Wohnungsgenossenschaft) are skipped elsewhere. If a portal
> can't find the city, the bot skips it and tells you on Telegram — search there in your
> browser and paste the result URL as `IMMOWELT_SEARCH_URL` / `IMMOSCOUT24_SEARCH_URL`
> (ImmoScout24 always needs this outside Göttingen). Update `SEARCH_POSTAL_CODES` too if
> you had Göttingen postcodes set.

> **SWB Göttingen has no online listings.** They allocate from a registered applicant
> pool. Do this ONCE, by hand: download the "Fragebogen für Wohnungsinteressenten" from
> [swb-goettingen.de](https://www.swb-goettingen.de/deutsch/wohnen/mieten/index.html)
> and submit it (Vermietungsteam: 0551 / 4967-20).

---

## Setup (5 minutes)

### 0. Prerequisites
- macOS with Python 3.10+ (`python3 --version`)
- A Telegram account

### 1. Install
```bash
git clone https://github.com/MRehanK209/germany-wohnungsbot.git
cd germany-wohnungsbot
./install.sh
source .venv/bin/activate
```

### 2. Connect Telegram & choose what to search for
1. In Telegram, open **@BotFather** → send `/newbot` → pick a name → copy the **token**.
2. Run the wizard — it takes the token, auto-detects your chat id, sends a test message,
   and asks **which city and apartments to search for**:
```bash
python -m bot.wizard
```
It asks for:

- **City:** any German city, for example `Göttingen`, `Berlin` or `München`.
- **Rooms (Zimmer):** `1-2` (1 to 2 rooms, the default), `1` (a studio / one-room apartment), `3-3.5` (a range), or `3+`. German counting —
  the living room counts, so a 2-bedroom + living room flat is a **3-Zimmer**.
- **Area range:** minimum `28` m² and maximum `50` m² by default, including both endpoints.
  Set either limit to `0` to remove it. Both `28.5` and `28,5` work.
- **Maximum listing age:** `7` days by default; `0` removes the date filter.
- **Monthly Warmmiete ceiling:** `600` € by default; `0` removes it. Unverified warm rents use the advertised price and are flagged in the alert.
- **Postal codes:** limit to specific PLZ in your chosen city, or leave blank for the whole city.
  Göttingen examples: `37073,37083`.
- Your name / email / phone (used only to fill contact-form fields).

(The wizard writes these to `.env`; they override the defaults in [config.yaml](config.yaml).)

### 3. Kleinanzeigen auto-messaging (login once)
```bash
python -m bot.credentials   # enter Kleinanzeigen email + password (password hidden)
./login.sh                  # opens Chrome; YOU solve the "human" checkbox and log in
```
`login.sh` stops the bot, opens the login window, and restarts the bot afterward — so
the browser profile isn't locked. Re-run it whenever the session expires. The session
is saved in `data/browser-profile` and reused (also headless).
*(The other platforms are links-only and need none of this.)*

### 4. Run automatically at login (recommended, macOS)
```bash
./install-autostart.sh
```
This installs a launchd agent (filling in your path automatically) so the bot starts
with your Mac and restarts itself if it crashes.
Stop it with `launchctl unload ~/Library/LaunchAgents/com.wohnungsbot.goettingen.plist`.
The **first run per platform is a baseline** (records what's already listed; never
auto-messages the backlog). After that, every **new** match is sent — and new
Kleinanzeigen matches are messaged automatically.

---

## Daily operations

For an always-on Linux VM, see [the free-hosting guide](docs/free-hosting.md)
and [the Ubuntu systemd service example](deploy/wohnungsbot.service.example).
Transfer the existing delivery database when moving from your Mac.

**What a Telegram notification looks like:**
```
🏠 Moderne 3-Zimmer-Wohnung mit Terrasse in Göttingen
🌐 New apartment — Kleinanzeigen
📍 37083 Göttingen
🚪 Rooms: 3
📐 82 m²
💶 1.440 €
🔗 https://www.kleinanzeigen.de/s-anzeige/...
✉️ Contact request: sent ✓
```
For Kleinanzeigen the `✉️ Contact request` line tells you whether the auto-message went
out (`sent ✓`, `not logged in`, `skipped (limit reached)`, or `unconfirmed`). For the
other platforms there's no contact line — tap the link and apply yourself.

**Change city, rooms, area range, listing age, rent ceiling or postal codes later:** re-run `python -m bot.wizard`, or
edit `.env` (`SEARCH_CITY`, `SEARCH_ROOMS`, `SEARCH_MIN_SIZE_SQM`, `SEARCH_MAX_SIZE_SQM`,
`SEARCH_MAX_AGE_DAYS`, `SEARCH_MAX_WARM_RENT_EUR`, `SEARCH_POSTAL_CODES`), then restart.

> **PLZ filter note:** it works where the platform shows a postal code — Kleinanzeigen,
> Immowelt, Vonovia. WG-Gesucht shows districts (e.g. "Geismar") not PLZ, so those listings
> come through regardless of the postal filter.

**Other tuning** (edit [config.yaml](config.yaml), then restart):
- `filters.max_warm_rent_eur: 600` — cap Warmmiete (`SEARCH_MAX_WARM_RENT_EUR` overrides it)
- `poll_interval_seconds: 180` — check other platforms more often (don't go below ~120)
- `platforms.<name>.enabled: false` — turn a platform off

**Check it's working:**
```bash
python -m bot.doctor      # tests Telegram + runs each enabled scraper once
```

**Logs:** `tail -f data/bot.log` · **Delivery cache:** `data/listings.db`.
Keep the database across restarts; deleting it makes previously seen listings appear new again.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| No Telegram messages | Run `python -m bot.doctor`; check the token/chat id in `.env`. Remember the **first run is a baseline** — new messages only start on genuinely new listings. |
| Kleinanzeigen: `not logged in` on the contact line | Session expired or never set. Run `./login.sh` and log in again. |
| Kleinanzeigen login checkbox won't clear / keeps flagging | It's their bot-detection. Move the mouse slowly, pause before ticking. If it persists, wait ~30 min and try `./login.sh` again; auto-messaging stays off until login succeeds (you still get the links). |
| Want to see it found something now | `python -m bot.doctor` prints how many listings each platform returns. |
| A platform suddenly finds 0 ads | The site changed its HTML. Check `data/bot.log`; selectors live in `bot/scrapers/<platform>.py`. |
| Too many / too few results | Re-run `python -m bot.wizard` to change search preferences, or edit the `SEARCH_*` settings in `.env`, including `SEARCH_MAX_WARM_RENT_EUR`, then restart. |
| Long gaps between scans / "quiet for hours" | Your Mac is sleeping — the bot freezes while asleep. `run.sh` runs `caffeinate -dimsu`, but a **closed lid still sleeps**. Keep the lid **open** and plugged in. To force it, run once: `sudo pmset -a disablesleep 1` (undo with `sudo pmset -a disablesleep 0`). For real 24/7 without tying up your Mac, run it on an always-on box — but prefer your home connection, since datacenter IPs get blocked by some portals. |
| "Only got one notification" | Telegram groups messages that arrive within seconds into one banner. All the individual apartment links are in the chat — scroll up. After the first batch you're only pinged on genuinely new matches. |
| ImmoScout24 keeps failing / Telegram warns about it | It's showing its captcha again. Stop the bot, run `./login.sh immoscout24`, solve it, then `./run.sh`. |
| Telegram says a platform "failed 3 scans in a row" | The site is down or changed. Check `data/bot.log`; selectors live in `bot/scrapers/<platform>.py`. You get a ✅ message when it recovers. |

## Notes

- Most platforms are **read-only** (scan + link). **Kleinanzeigen is different**: the
  bot logs into your account and auto-sends your message to new matches. That plus the
  30s scan cadence violates Kleinanzeigen's terms and carries a real risk of the
  account being flagged or banned — that risk is yours. Dial the interval up and keep
  `contact.max_per_hour` modest to reduce it.
- Watch your Kleinanzeigen inbox and reply fast when a landlord answers — the bot gets
  you in early; a quick, human follow-up wins the viewing.
