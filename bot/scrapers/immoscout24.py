"""ImmobilienScout24 — hinter AWS-WAF-Bot-Schutz, deshalb via echtem Browser.

Der persistente Chromium (data/browser-profile) besteht die JS-Challenge in
der Regel automatisch; eingeloggt zu sein (python -m bot.login) hilft
zusätzlich. Geparst wird absichtlich locker über /expose/-Links + Kartentext,
weil IS24 seine CSS-Klassen häufig ändert.
"""

import re

from bs4 import BeautifulSoup

from ..location import immoscout24_search_url
from ..dates import json_ld_dates, newest_first, publication_date
from ..models import Listing
from ..rent import warm_rent_from_html
from .base import BaseScraper, parse_rooms


class ImmoScout24(BaseScraper):
    name = "immoscout24"
    uses_browser = True

    def enrich_rent(self, listing: Listing, browser=None):
        if listing.warm_rent_eur is not None or browser is None:
            return
        page = browser.page()
        try:
            page.goto(listing.url, wait_until="domcontentloaded")
            listing.warm_rent_eur = warm_rent_from_html(page.content(), self.name)
        finally:
            page.close()

    def search_url(self) -> str:
        f = self.cfg["filters"]
        rooms_to = f"{f['max_rooms']:.1f}" if f["max_rooms"] < 99 else ""
        url = f"{immoscout24_search_url(self.city)}?numberofrooms={f['min_rooms']:.1f}-{rooms_to}"
        min_area, max_area = f.get("min_size_sqm"), f.get("max_size_sqm")
        if min_area or max_area:
            url += (f"&livingspace={f'{min_area:.1f}' if min_area else ''}-"
                    f"{f'{max_area:.1f}' if max_area else ''}")
        return url + "&sorting=2"

    def check_location(self):
        self.search_url()

    def fetch(self, browser=None) -> list[Listing]:
        if browser is None:
            raise RuntimeError("ImmoScout24 needs the browser (AWS WAF protection). "
                               "Check the headless/auto_contact configuration.")
        page = browser.page()
        try:
            page.goto(self.search_url(), wait_until="domcontentloaded")
            try:
                page.wait_for_selector('a[href*="/expose/"]', timeout=30000)
            except Exception:
                shot = browser.screenshot_failure(page, "immoscout24-search")
                raise RuntimeError(
                    "Search results did not load — most likely bot protection/captcha. "
                    f"Screenshot: {shot}. Tip: run `python -m bot.login` once and sign in "
                    "at ImmoScout24 (solve the captcha by hand there)."
                )
            found: dict[str, Listing] = {}
            dates = json_ld_dates(BeautifulSoup(page.content(), "lxml"), self.search_url())
            for a in page.query_selector_all('a[href*="/expose/"]'):
                href = a.get_attribute("href") or ""
                m = re.search(r"/expose/(\d+)", href)
                if not m:
                    continue
                lid = m.group(1)
                card_html = a.evaluate("el => (el.closest('article, li') || el).outerHTML") or ""
                card = BeautifulSoup(card_html, "lxml")
                text = re.sub(r"\s+", " ", card.get_text(" ", strip=True))
                if lid in found and len(text) <= len(found[lid].raw.get("text", "")):
                    continue
                price_m = re.search(r"(\d[\d.,]*\s*€)", text)
                rooms_m = re.search(r"(\d+(?:[.,]\d)?)\s*Zi", text)
                size_m = re.search(r"(\d+(?:[.,]\d+)?\s*m²)", text)
                title = (a.get_attribute("title") or "").strip() or text[:90]
                found[lid] = Listing(
                    platform=self.name,
                    listing_id=lid,
                    url=f"https://www.immobilienscout24.de/expose/{lid}",
                    title=title.strip() or "ImmoScout24-Wohnung",
                    price=price_m.group(1) if price_m else "",
                    rooms=parse_rooms(rooms_m.group(1)) if rooms_m else None,
                    size=size_m.group(1) if size_m else "",
                    raw={"text": text},
                    published_at=publication_date(
                        card, f"https://www.immobilienscout24.de/expose/{lid}", dates,
                    ),
                )
            return newest_first(found.values())
        finally:
            page.close()
