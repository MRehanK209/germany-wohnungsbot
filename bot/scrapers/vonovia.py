"""Vonovia — JSON-API, kein Bot-Schutz.

Seit 2026 verlangt /api/real-estate/list einen kurzlebigen Such-Token
(GET /api/real-estate/search-token -> {"token", "ttl"}), der im Header
X-VON-Search-Token mitgeschickt wird — genau wie es die Website selbst macht.
"""

from urllib.parse import quote

from ..dates import newest_first, parse_listing_date
from ..models import Listing
from ..money import parse_euro_amount
from .base import BaseScraper

BASE = "https://www.vonovia.de"
TOKEN_URL = f"{BASE}/api/real-estate/search-token"
API = (f"{BASE}/api/real-estate/list"
       "?rentType=miete&city={city}&immoType=wohnung&offset=0&limit=50")


class Vonovia(BaseScraper):
    name = "vonovia"

    def search_token(self) -> str:
        token = (self.get(TOKEN_URL).json() or {}).get("token")
        if not token:
            raise RuntimeError("Vonovia did not issue a search token.")
        return token

    def fetch(self, browser=None) -> list[Listing]:
        data = self.get(API.format(city=quote(self.city)), headers={"X-VON-Search-Token": self.search_token(),
                                      "Accept": "application/json"}).json()
        out = []
        for r in data.get("results", []):
            if not r.get("wrk_id"):
                continue
            price = r.get("preis")
            size = r.get("groesse")
            out.append(Listing(
                platform=self.name,
                listing_id=str(r["wrk_id"]),
                url=f"{BASE}/zuhause-finden/immobilien/{r.get('slug', '')}",
                title=r.get("titel") or "Vonovia-Wohnung",
                price=f"{price} €" if price else "",
                warm_rent_eur=parse_euro_amount(r.get("warmmiete") or r.get("warmRent")),
                rooms=float(r["anzahl_zimmer"]) if r.get("anzahl_zimmer") else None,
                size=f"{size} m²" if size else "",
                address=", ".join(filter(None, [(r.get("strasse") or "").strip(),
                                                f"{r.get('plz', '')} {r.get('ort', '')}".strip()])),
                published_at=parse_listing_date(
                    r.get("datePosted") or r.get("datePublished")
                    or r.get("published_at") or r.get("publishedAt")
                ),
            ))
        return newest_first(out)
