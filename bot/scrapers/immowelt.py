"""Immowelt.de — SEO-Suchseite (server-rendered, ohne Bot-Schutz).

Nur die /suche/...-URLs funktionieren ohne Browser; Exposé-Seiten sind
DataDome-geschützt (die Kontaktaufnahme läuft deshalb über Playwright).
CSS-Klassen sind gehasht und instabil — nur data-testid verwenden.
"""

import re

from bs4 import BeautifulSoup

from ..location import immowelt_search_url
from ..dates import json_ld_dates, newest_first, publication_date
from ..models import Listing
from .base import BaseScraper, clean, parse_rooms


class Immowelt(BaseScraper):
    name = "immowelt"

    def search_url(self) -> str:
        # No room segment: Immowelt's `zimmer-N` only matches N..N.5, which can't
        # express an arbitrary range. Fetch all apartments in the city and let the
        # room filter (passes_filters) narrow to whatever count the user chose.
        return immowelt_search_url(self.city, self.get)

    def check_location(self):
        self.search_url()

    def fetch(self, browser=None) -> list[Listing]:
        soup = BeautifulSoup(self.get(self.search_url()).text, "lxml")
        dates = json_ld_dates(soup, self.search_url())
        out = []
        for card in soup.select('div[data-testid="serp-core-classified-card-testid"]'):
            link = card.select_one('a[data-testid="card-mfe-covering-link-testid"]')
            if not link or not link.get("href"):
                continue
            url = link["href"]
            listing_id = url.rstrip("/").rsplit("/", 1)[-1]
            summary = link.get("title", "")  # z.B. "Wohnung zur Miete - Göttingen - 773 € - 3 Zimmer, 77,5 m², ..."

            price_el = card.select_one('div[data-testid="cardmfe-price-testid"] > div')
            facts_el = card.select_one('div[data-testid="cardmfe-keyfacts-testid"]')
            addr_el = card.select_one('div[data-testid="cardmfe-description-box-address"]')
            facts = clean(facts_el.get_text(" ")) if facts_el else summary

            rooms_m = re.search(r"(\d+(?:[.,]\d)?)\s*Zimmer", facts)
            size_m = re.search(r"(\d+(?:[.,]\d+)?\s*m²)", facts)
            out.append(Listing(
                platform=self.name,
                listing_id=listing_id,
                url=url,
                title=clean(summary.split(" - ")[0]) if summary else "Wohnung zur Miete",
                price=clean(price_el.get_text()) if price_el else "",
                rooms=parse_rooms(rooms_m.group(1)) if rooms_m else None,
                size=size_m.group(1) if size_m else "",
                address=clean(addr_el.get_text()) if addr_el else "",
                published_at=publication_date(card, url, dates),
            ))
        return newest_first(out)
