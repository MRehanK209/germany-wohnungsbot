"""Read warm rent from a listing's own fields, excluding related adverts."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .money import parse_euro_amount


def warm_rent_from_html(source: str, platform: str) -> float | None:
    soup = BeautifulSoup(source, "lxml")
    if platform == "kleinanzeigen":
        scope = soup.select_one("#viewad-product, #viewad-details")
        description = soup.select_one("#viewad-description-text")
    elif platform == "wg_gesucht":
        scope = soup.select_one("#main_column, #main_content")
        description = soup.select_one("#ad_description_text")
    else:
        scope = soup.select_one("main, .immomakler-single, article.type-immomakler_object")
        description = scope.select_one('[itemprop="description"], .property-description') if scope else None
    if scope is None:
        return None

    pairs = []
    for row in scope.select(".addetailslist--detail"):
        value = row.select_one(".addetailslist--detail--value")
        if value:
            label = " ".join(str(text) for text in row.find_all(string=True, recursive=False))
            pairs.append((label, value.get_text(" ", strip=True)))
    for label in scope.select(".key_fact_detail"):
        value = label.parent.select_one(".key_fact_value")
        if value:
            pairs.append((label.get_text(" ", strip=True), value.get_text(" ", strip=True)))
    for label in scope.select("dt"):
        value = label.find_next_sibling("dd")
        if value:
            pairs.append((label.get_text(" ", strip=True), value.get_text(" ", strip=True)))
    for row in scope.select("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) == 2:
            pairs.append((cells[0].get_text(" ", strip=True), cells[1].get_text(" ", strip=True)))
    for row in scope.select(".property-data .row"):
        label, value = row.select_one(".dt"), row.select_one(".dd")
        if label and value:
            pairs.append((label.get_text(" ", strip=True), value.get_text(" ", strip=True)))

    text = description.get_text(" ", strip=True) if description else ""
    labels = " ".join(label for label, value in pairs)
    heating_text = re.sub(r"\s+", " ", text + " " + labels).casefold()
    # A Gesamtmiete can exclude heating, so it alone is insufficient.
    if re.search(
        r"(?:heizkosten|heizung|heating costs?)[^.!?;,\n]{0,40}(?:nicht\b|separat|extra|not included)"
        r"|(?:zzgl\.?|zuzüglich|ohne|exklusive|excluding).{0,20}(?:heizkosten|heizung|heating)",
        heating_text,
    ):
        return None
    heating_included = bool(re.search(
        r"(?:heizkosten|heizung|heating costs?).{0,40}(?:enthalten|inbegriffen|included)"
        r"|(?:inkl\.?|inklusive|einschließlich|including).{0,25}(?:heizkosten|heizung|heating)",
        heating_text,
    ))
    warm, totals, components = [], [], {}
    for label, value in pairs:
        name = re.sub(r"\s+", " ", label).strip(" :").casefold()
        amount = parse_euro_amount(value)
        if amount is None:
            continue
        if name in ("warmmiete", "bruttowarmmiete", "warm rent"):
            warm.append(amount)
        elif name == "gesamtmiete":
            totals.append(amount)
        elif name == "kaltmiete":
            components["cold"] = amount
        elif name.startswith("nebenkosten") or name.startswith("betriebskosten"):
            components["charges"] = amount
        elif name == "heizkosten":
            components["heating"] = amount

    amount_pattern = r"([0-9][0-9., ]*)\s*(?:€|EUR\b|Euro\b)"
    for pattern in (
        r"\b(?:warmmiete|warm rent)\s*(?:(?:beträgt|ist|von|liegt bei)\s*|:\s*)?" + amount_pattern,
        amount_pattern + r"\s*(?:warm\b|warmmiete\b|bruttowarm\b)",
    ):
        for match in re.finditer(pattern, text, re.I):
            amount = parse_euro_amount(match[1])
            if amount is not None:
                warm.append(amount)
    if warm:
        return max(warm) if max(warm) > 0 else None
    if heating_included and totals:
        return max(totals) if max(totals) > 0 else None
    if "cold" in components and "charges" in components:
        if heating_included:
            return round(components["cold"] + components["charges"], 2)
        if components.get("heating", 0) > 0:
            return round(components["cold"] + components["charges"] + components["heating"], 2)
    return None
