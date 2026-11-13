"""Kleinanzeigen.de — Mietwohnungen in SEARCH_CITY (Göttingen = Ortscode l3130).

Server-rendered. Room and living-area ranges are applied in the search URL.
"""

import json

from bs4 import BeautifulSoup

from ..location import kleinanzeigen_location_id, slugify
from ..dates import json_objects, newest_first, parse_listing_date, publication_date
from ..models import Listing
from .base import BaseScraper, clean, parse_rooms

BASE = "https://www.kleinanzeigen.de"


def _astro_value(value):
    """Decode Astro's [type, value] serialization without executing scripts."""
    if isinstance(value, dict):
        return {key: _astro_value(child) for key, child in value.items()}
    if isinstance(value, list):
        if len(value) == 2 and type(value[0]) is int and value[0] in (0, 1):
            return _astro_value(value[1])
        return [_astro_value(child) for child in value]
    return value


def _listing_dates(soup):
    dates = {}
    for island in soup.select("astro-island[props]"):
        props = island.get("props", "")
        if "sortingDate" not in props:
            continue
        try:
            data = _astro_value(json.loads(props))
        except (TypeError, ValueError):
            continue
        for record in json_objects(data):
            published = parse_listing_date(record.get("sortingDate"))
            listing_id = record.get("id")
            if listing_id is not None and published is not None:
                key = str(listing_id)
                dates[key] = min(dates.get(key, published), published)
    return dates


class Kleinanzeigen(BaseScraper):
    name = "kleinanzeigen"

    def search_url(self) -> str:
        filters = self.cfg["filters"]
        min_rooms, max_rooms = filters["min_rooms"], filters["max_rooms"]
        upper = f"{max_rooms:g}" if max_rooms < 99 else ""
        loc_id = kleinanzeigen_location_id(self.city, self.get)
        url = (f"{BASE}/s-wohnung-mieten/{slugify(self.city)}/anzeige:angebote/"
               f"c203l{loc_id}+wohnung_mieten.zimmer_d:{min_rooms:g}%2C{upper}")
        min_area, max_area = filters.get("min_size_sqm"), filters.get("max_size_sqm")
        if min_area or max_area:
            area_from = f"{min_area:g}" if min_area else ""
            area_to = f"{max_area:g}" if max_area else ""
            url += f"+wohnung_mieten.qm_d:{area_from}%2C{area_to}"
        return url + "?sortingField=SORTING_DATE"

    def check_location(self):
        kleinanzeigen_location_id(self.city, self.get)

    def fetch(self, browser=None) -> list[Listing]:
        soup = BeautifulSoup(self.get(self.search_url()).text, "lxml")
        dates = _listing_dates(soup)
        out = []
        for card in soup.select("article[data-adid]"):
            adid = card.get("data-adid")
            href = card.get("data-href", "")
            if not adid or not href:
                continue
            # "TOP"-Anzeigen sind bezahlte Platzierungen, die den Filter ignorieren
            if card.select_one(".aditem-image--badges--badge-topad"):
                continue
            if any(clean(badge.get_text()) == "TOP" for badge in card.select(".bg-accent")):
                continue
            title_el = card.select_one("h2 a, h3 a")
            title = clean(title_el.get_text()) if title_el else ""
            price_el = card.select_one("p.aditem-main--middle--price-shipping--price, p.text-title3")
            tags_el = card.select_one("p.aditem-main--middle--tags, p.font-strong.text-onSurfaceSubdued")
            tags = clean(tags_el.get_text()) if tags_el else ""
            rooms, size = None, ""
            for part in tags.split("·"):
                part = part.strip()
                if "Zi" in part:
                    rooms = parse_rooms(part)
                elif "m²" in part:
                    size = part
            addr_el = card.select_one("div.aditem-main--top--left")
            if addr_el is None:
                location_icon = card.select_one('[data-title="locationOutline"]')
                addr_el = location_icon.parent if location_icon else None
            published = dates.get(str(adid)) or publication_date(card, BASE + href, {})
            if published is None:
                # Legacy cards show the listing date beside the location.
                date_el = card.select_one(".aditem-main--top--right")
                published = parse_listing_date(date_el.get_text(" ", strip=True)) if date_el else None
            out.append(Listing(
                platform=self.name,
                listing_id=adid,
                url=BASE + href,
                title=title,
                price=clean(price_el.get_text()) if price_el else "",
                rooms=rooms,
                size=size,
                address=clean(addr_el.get_text()) if addr_el else "",
                published_at=published,
            ))
        return newest_first(out)
