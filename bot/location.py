"""Where to search: the city from SEARCH_CITY (.env), default Göttingen.

Each portal identifies a city by its own internal id. Göttingen's ids are built
in (no lookups for the default setup); any other city is resolved once per run
through the portal's own location autocomplete and cached in memory.

Portals whose location can't be derived from a name accept a pasted search URL
in .env instead (IMMOWELT_SEARCH_URL, IMMOSCOUT24_SEARCH_URL).
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit, urlunsplit

DEFAULT_CITY = "Göttingen"

# Built-in ids for the default city (verified against each portal).
GOETTINGEN = {
    "kleinanzeigen": "3130",
    "wg_gesucht": "49",
    "immowelt": "https://www.immowelt.de/suche/mieten/wohnung/niedersachsen/gottingen-37073/ad08de1164",
    "immoscout24": "https://www.immobilienscout24.de/Suche/de/niedersachsen/goettingen-kreis/goettingen/wohnung-mieten",
}

_cache: dict[tuple[str, str], str] = {}


class LocationError(RuntimeError):
    """The configured city could not be found on a portal."""


def city_name(cfg: dict) -> str:
    return (cfg.get("city") or DEFAULT_CITY).strip()


def is_default_city(city: str) -> bool:
    return slugify(city) in ("goettingen", "gottingen")


def slugify(city: str) -> str:
    """'Göttingen' -> 'goettingen', 'Frankfurt am Main' -> 'frankfurt-am-main'."""
    s = city.strip().casefold()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _key(city: str) -> str:
    return slugify(city)


def _cached(platform: str, city: str, resolve) -> str:
    key = (platform, _key(city))
    if key not in _cache:
        _cache[key] = resolve()
    return _cache[key]


def _env_url(name: str) -> str | None:
    from .config import env
    value = (env(name) or "").strip()
    return value or None


def _strip_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def kleinanzeigen_location_id(city: str, get) -> str:
    """Kleinanzeigen 'Ortscode' (the number after 'l' in c203l3130)."""
    if is_default_city(city):
        return GOETTINGEN["kleinanzeigen"]

    def resolve():
        data = get(f"https://www.kleinanzeigen.de/s-ort-empfehlungen.json?query={quote(city)}").json()
        wanted = city.casefold()
        exact, first_part = None, None
        for key, label in (data or {}).items():
            loc_id = str(key).lstrip("_")
            if loc_id in ("", "0"):
                continue  # "Deutschland"
            label = str(label)
            if label.casefold() == wanted:
                exact = exact or loc_id
            elif label.split(" - ")[0].strip().casefold() == wanted:
                first_part = first_part or loc_id
        found = exact or first_part
        if not found:
            raise LocationError(f"Kleinanzeigen has no location called '{city}'.")
        return found

    return _cached("kleinanzeigen", city, resolve)


def wg_gesucht_city_id(city: str, get) -> str:
    if is_default_city(city):
        return GOETTINGEN["wg_gesucht"]

    def resolve():
        data = get(f"https://www.wg-gesucht.de/api/location/cities/names/{quote(city)}",
                   headers={"Accept": "application/json"}).json()
        cities = ((data or {}).get("_embedded") or {}).get("cities") or []
        wanted = city.casefold()
        for c in cities:
            if c.get("country_code") == "de" and str(c.get("city_name", "")).casefold() == wanted:
                return str(c["city_id"])
        for c in cities:  # e.g. "Frankfurt" -> "Frankfurt am Main"
            if c.get("country_code") == "de" and str(c.get("city_name", "")).casefold().startswith(wanted):
                return str(c["city_id"])
        raise LocationError(f"WG-Gesucht has no city called '{city}'.")

    return _cached("wg_gesucht", city, resolve)


def immowelt_search_url(city: str, get) -> str:
    override = _env_url("IMMOWELT_SEARCH_URL")
    if override:
        return _strip_query(override)
    if is_default_city(city):
        return GOETTINGEN["immowelt"]

    def resolve():
        # Immowelt's legacy list URL redirects to the current search page.
        r = get(f"https://www.immowelt.de/liste/{slugify(city)}/wohnungen/mieten")
        final = str(getattr(r, "url", ""))
        if "/suche/mieten/wohnung/" not in final:
            raise LocationError(
                f"Immowelt could not find '{city}'. Open immowelt.de, search apartments to "
                "rent there, and paste the result URL as IMMOWELT_SEARCH_URL in .env.")
        return _strip_query(final)

    return _cached("immowelt", city, resolve)


def immoscout24_search_url(city: str) -> str:
    override = _env_url("IMMOSCOUT24_SEARCH_URL")
    if override:
        return _strip_query(override)
    if is_default_city(city):
        return GOETTINGEN["immoscout24"]
    raise LocationError(
        f"ImmoScout24 needs its own search URL for '{city}'. Open immobilienscout24.de, "
        "search apartments to rent there, and paste the result URL as "
        "IMMOSCOUT24_SEARCH_URL in .env.")
