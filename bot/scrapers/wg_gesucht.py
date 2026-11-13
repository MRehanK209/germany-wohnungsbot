"""WG-Gesucht.de — Kategorie 1 = Studios, 2 = Wohnungen; Stadt-ID aus SEARCH_CITY (Göttingen = 49).

Kein eigener 3-Zimmer-Filter in der URL; die Zimmerzahl steht im Kartentitel
("3-Zimmer-Wohnung | Göttingen ...") und wird hier geparst — der globale
Filter erledigt den Rest. Achtung: WG-Gesucht ratelimitet bei hohem Volumen.
"""

import re

from bs4 import BeautifulSoup

from ..location import slugify, wg_gesucht_city_id
from ..dates import json_ld_dates, newest_first, publication_date
from ..models import Listing
from .base import BaseScraper, clean, parse_rooms

BASE = "https://www.wg-gesucht.de"


class WgGesucht(BaseScraper):
    name = "wg_gesucht"

    def search_urls(self) -> list[str]:
        filters = self.cfg["filters"]
        city_id = wg_gesucht_city_id(self.city, self.get)
        # The name part is cosmetic (WG-Gesucht routes by id); match its canonical form.
        slug = "-".join(part.capitalize() for part in slugify(self.city).split("-"))
        urls = []
        if filters["min_rooms"] < 2:
            urls.append(f"{BASE}/1-zimmer-wohnungen-in-{slug}.{city_id}.1.1.0.html")
        if filters["max_rooms"] >= 2:
            urls.append(f"{BASE}/wohnungen-in-{slug}.{city_id}.2.1.0.html")
        return [url + "?sort_column=0&sort_order=0" for url in urls]

    def check_location(self):
        wg_gesucht_city_id(self.city, self.get)

    def fetch(self, browser=None) -> list[Listing]:
        listings = {}
        for url in self.search_urls():
            for listing in self._fetch_page(url):
                listings[listing.listing_id] = listing
        return newest_first(listings.values())

    def _fetch_page(self, url: str) -> list[Listing]:
        soup = BeautifulSoup(self.get(url).text, "lxml")
        dates = json_ld_dates(soup, BASE)
        out = []
        for card in soup.select(".offer_list_item[data-id]"):
            if "panel-deactivated" in " ".join(card.get("class", [])):
                continue
            ad_id = card.get("data-id")
            link = card if card.name == "a" else card.select_one("h2.truncate_title a")
            if not ad_id or not link or not link.get("href"):
                continue
            href = link["href"]
            listing_url = href if href.startswith("http") else BASE + "/" + href.lstrip("/")
            info_el = card.select_one(".card-details-text, div.col-xs-11 > span")
            info = clean(info_el.get_text()) if info_el else ""
            parts = [p.strip() for p in re.split(r"[|·]", info)]
            rooms = parse_rooms(parts[0]) if parts and "Zimmer" in parts[0] else None
            address = ", ".join(parts[1:]) if len(parts) > 1 else ""

            title_el = card.select_one("h2")
            price_el = card.select_one(".price-row .card-main-text, div.row.noprint.middle div.col-xs-3 b")
            size_el = card.select_one(".size-value, div.row.noprint.middle div.col-xs-3.text-right b")
            out.append(Listing(
                platform=self.name,
                listing_id=ad_id,
                url=listing_url,
                title=clean((title_el or link).get_text()),
                price=clean(price_el.get_text()) if price_el else "",
                rooms=rooms,
                size=clean(size_el.get_text()) if size_el else "",
                address=address,
                published_at=publication_date(card, listing_url, dates),
            ))
        return out
