"""Parse advertised monthly euro amounts without dropping decimal cents."""

from __future__ import annotations

import math
import re


def parse_euro_amount(value) -> float | None:
    """Accept plain amounts, German/English separators and euro suffixes."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        amount = float(value)
    else:
        text = re.sub(r"\s+", " ", str(value)).strip()
        text = re.sub(r"([,.])-(?=\s*(?:€|EUR|$))", r"\g<1>00", text, flags=re.I)
        match = re.fullmatch(
            r"(?:€\s*)?([+]?\d[\d., ]*)(?:\s*(?:€|EUR))?"
            r"(?:\s*(?:VB|/Monat|pro Monat|monatlich))?",
            text, re.I,
        )
        if not match:
            return None
        number = match[1].replace(" ", "")
        if re.fullmatch(r"[+]?\d+(?:[.,]\d{1,2})?", number):
            number = number.replace(",", ".")
        elif re.fullmatch(r"[+]?\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?", number):
            number = number.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"[+]?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?", number):
            number = number.replace(",", "")
        else:
            return None
        amount = float(number)
    return amount if math.isfinite(amount) and amount >= 0 else None
