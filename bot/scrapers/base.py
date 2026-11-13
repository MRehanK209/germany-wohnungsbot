from __future__ import annotations

import math
import re

import httpx

from ..location import city_name, slugify
from ..models import Listing
from ..rent import warm_rent_from_html

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


def parse_rooms(text) -> float | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    m = re.search(r"(\d+(?:[.,]\d)?)", str(text))
    return float(m.group(1).replace(",", ".")) if m else None


def parse_size_sqm(text) -> float | None:
    """Parse a living-area field, e.g. '28,5 m²', '28.5 m2' or '28'."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        value = float(text)
    else:
        match = re.search(r"-?\d+(?:[.,]\d+)?", str(text))
        if not match:
            return None
        value = float(match.group().replace(",", "."))
    return value if math.isfinite(value) and value > 0 else None


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text).strip() if text else ""


class BaseScraper:
    name = "base"
    uses_browser = False  # True -> fetch() gets a Playwright Browser
    local_to: str | None = None  # e.g. "Göttingen" for a local housing co-op

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.city = city_name(cfg)

    @classmethod
    def serves_city(cls, city: str) -> bool:
        return cls.local_to is None or slugify(cls.local_to) == slugify(city)

    def check_location(self):
        """Resolve the configured city on this portal; raises LocationError if unknown."""

    def fetch(self, browser=None) -> list[Listing]:
        raise NotImplementedError

    def enrich_rent(self, listing: Listing, browser=None):
        if listing.warm_rent_eur is None:
            listing.warm_rent_eur = warm_rent_from_html(self.get(listing.url).text, self.name)

    def get(self, url: str, **kw) -> httpx.Response:
        headers = {**HEADERS, **kw.pop("headers", {})}
        r = httpx.get(url, headers=headers, follow_redirects=True, timeout=30, **kw)
        r.raise_for_status()
        return r
