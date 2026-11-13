"""Publication dates reported by rental sites, separate from first_seen."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urldefrag, urljoin
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_listing_date(value, *, now: datetime | None = None) -> datetime | None:
    """Parse explicit publication fields; German dates use Europe/Berlin."""
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, date):
        result = datetime.combine(value, datetime.min.time())
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value / 1000 if value > 1e12 else value, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str) and value.strip():
        text = re.sub(r"\s+", " ", value).strip()
        try:
            result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            local_now = (now or utc_now()).astimezone(BERLIN)
            match = re.fullmatch(
                r"(heute|gestern|today|yesterday)(?:,?\s+(\d{1,2}:\d{2}))?",
                text, re.I,
            )
            if match:
                day = local_now.date() - timedelta(
                    days=match[1].lower() in ("gestern", "yesterday")
                )
                result = datetime.combine(day, datetime.min.time())
                if match[2]:
                    try:
                        clock = datetime.strptime(match[2], "%H:%M").time()
                    except ValueError:
                        return None
                    result = datetime.combine(day, clock)
            else:
                result = None
                for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y, %H:%M",
                            "%d.%m.%Y", "%d.%m.%y"):
                    try:
                        result = datetime.strptime(text, fmt)
                        break
                    except ValueError:
                        continue
                if result is None:
                    return None
    else:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=BERLIN)
    return result.astimezone(UTC)


def newest_first(listings):
    """Known publication dates descending; undated results last, stably."""
    oldest = datetime.min.replace(tzinfo=UTC)
    return sorted(
        listings,
        key=lambda listing: parse_listing_date(listing.published_at) or oldest,
        reverse=True,
    )


def json_objects(value):
    """Walk JSON without executing any code embedded in a page."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from json_objects(child)


def json_ld_dates(soup, base_url: str) -> dict[str, datetime]:
    """Match each listing's own datePosted/datePublished to its URL."""
    dates = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text().strip().rstrip(";"))
        except (ValueError, TypeError):
            continue
        for record in json_objects(data):
            published = parse_listing_date(record.get("datePosted") or record.get("datePublished"))
            url = record.get("url") or record.get("@id")
            if published is not None and isinstance(url, str):
                key = urldefrag(urljoin(base_url, url))[0]
                dates[key] = min(dates.get(key, published), published)
    return dates


def publication_date(element, url: str, dates: dict[str, datetime]) -> datetime | None:
    """Use explicit publication markup, never availability or online activity."""
    published = dates.get(urldefrag(url)[0])
    if published is not None:
        return published
    node = element.select_one(
        '[itemprop="datePosted"], [itemprop="datePublished"], '
        "time[pubdate], time.published, time.entry-date, "
        "[data-published-at], [data-date-posted]"
    )
    if node is None:
        return None
    return parse_listing_date(
        node.get("datetime") or node.get("content")
        or node.get("data-published-at") or node.get("data-date-posted")
        or node.get_text(" ", strip=True)
    )
