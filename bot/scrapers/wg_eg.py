"""Wohnungsgenossenschaft eG Göttingen — WordPress + immomakler-Plugin.

Server-rendered, kein Schutz. Stellplätze/Garagen werden übersprungen.
"""

from bs4 import BeautifulSoup

from ..dates import json_ld_dates, newest_first, publication_date
from ..models import Listing
from ..money import parse_euro_amount
from .base import BaseScraper, clean, parse_rooms

URL = "https://wg-goe.de/wohnungsangebote/"

SKIP_WORDS = ("parken", "stellplatz", "garage", "fahrrad")


class WgEg(BaseScraper):
    name = "wg_eg"
    local_to = "Göttingen"

    def fetch(self, browser=None) -> list[Listing]:
        soup = BeautifulSoup(self.get(URL).text, "lxml")
        dates = json_ld_dates(soup, URL)
        out = []
        for container in soup.select("div.property-container[id]"):
            link = container.select_one("h3.property-title a")
            if not link or not link.get("href"):
                continue
            subtitle_el = container.select_one("div.property-subtitle")
            subtitle = clean(subtitle_el.get_text()) if subtitle_el else ""
            title = clean(link.get_text())
            if any(w in (title + " " + subtitle).lower() for w in SKIP_WORDS):
                continue

            def data_value(key):
                el = container.select_one(f"div.row.data-{key} .dd")
                return clean(el.get_text()) if el else ""

            out.append(Listing(
                platform=self.name,
                listing_id=container["id"],
                url=link["href"],
                title=title,
                price=data_value("kaltmiete"),
                warm_rent_eur=parse_euro_amount(data_value("warmmiete")),
                rooms=parse_rooms(data_value("zimmer")) or None,
                size=data_value("wohnflaeche"),
                address=subtitle,
                published_at=publication_date(container, link["href"], dates),
            ))
        return newest_first(out)
