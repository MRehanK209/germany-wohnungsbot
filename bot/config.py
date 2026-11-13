from __future__ import annotations

import math
import os
import pathlib

import yaml
from dotenv import load_dotenv

from .money import parse_euro_amount

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

load_dotenv(ROOT / ".env")


def load_config() -> dict:
    path = ROOT / "config.yaml"
    if not path.exists():
        raise SystemExit("config.yaml is missing. See the README / run install.sh.")
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Apply the search preferences the user chose at setup (.env) so they
    # drive BOTH the search URLs and the result filter — not just the filter.
    cfg["filters"] = resolve_filters(cfg)
    cfg["city"] = (env("SEARCH_CITY") or "").strip() or cfg.get("city") or "Göttingen"
    return cfg


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        raise SystemExit(
            f"Environment variable {name} is missing. Add it to the .env file "
            f"(template: .env.example, or run `python -m bot.wizard`)."
        )
    return value


def parse_rooms_spec(spec: str) -> tuple[float, float]:
    """'3' -> (3,3); '3-3.5' / '3 - 3,5' -> (3,3.5); '2+' -> (2, 99); '' -> (0, 99)."""
    s = (spec or "").replace(",", ".").strip()
    if not s:
        return 0.0, 99.0
    if "-" in s:
        a, b = s.split("-", 1)
        return float(a.strip()), float(b.strip())
    if s.endswith("+"):
        return float(s[:-1].strip()), 99.0
    v = float(s)
    return v, v


def parse_size_limit_spec(spec: str) -> float:
    """Living-area limit in m², allowing German decimal commas; 0 disables it."""
    try:
        value = float(spec.strip().replace(",", "."))
    except ValueError:
        raise ValueError("Area limit must be a non-negative number.") from None
    if not math.isfinite(value) or value < 0:
        raise ValueError("Area limit must be a non-negative number.")
    return value


def resolve_filters(cfg: dict) -> dict:
    """Effective filters: config.yaml defaults, overridden by what setup wrote to .env
    (SEARCH_ROOMS, SEARCH_MIN_SIZE_SQM, SEARCH_MAX_SIZE_SQM,
     SEARCH_MAX_AGE_DAYS, SEARCH_MAX_WARM_RENT_EUR, SEARCH_POSTAL_CODES)."""
    f = dict(cfg.get("filters") or {})
    rooms = env("SEARCH_ROOMS")
    if rooms:
        f["min_rooms"], f["max_rooms"] = parse_rooms_spec(rooms)
    for bound in ("min", "max"):
        size = env(f"SEARCH_{bound.upper()}_SIZE_SQM")
        if size and size.strip():
            f[f"{bound}_size_sqm"] = parse_size_limit_spec(size)
    min_size, max_size = f.get("min_size_sqm"), f.get("max_size_sqm")
    if min_size and max_size and min_size > max_size:
        raise ValueError("Minimum area cannot exceed maximum area.")
    max_age = env("SEARCH_MAX_AGE_DAYS")
    if max_age and max_age.strip():
        f["max_listing_age_days"] = parse_max_age_spec(max_age)
    max_rent = env("SEARCH_MAX_WARM_RENT_EUR")
    if max_rent and max_rent.strip():
        f["max_warm_rent_eur"] = parse_rent_limit_spec(max_rent)
    elif f.get("max_warm_rent_eur") is not None:
        f["max_warm_rent_eur"] = parse_rent_limit_spec(f["max_warm_rent_eur"])
    plz = env("SEARCH_POSTAL_CODES")
    if plz is not None:
        f["postal_codes"] = [p.strip() for p in plz.split(",") if p.strip()]
    f.setdefault("postal_codes", f.get("postal_codes") or [])
    return f


def parse_max_age_spec(spec: str) -> int:
    """Maximum listing age in whole days; 0 disables the age limit."""
    try:
        days = int(spec.strip())
    except ValueError:
        raise ValueError("Maximum listing age must be a non-negative whole number of days.") from None
    if days < 0:
        raise ValueError("Maximum listing age must be a non-negative whole number of days.")
    return days


def parse_rent_limit_spec(spec: str) -> float:
    """Monthly Warmmiete ceiling; 0 disables the ceiling."""
    amount = parse_euro_amount(spec)
    if amount is None:
        raise ValueError("Rent ceiling must be a non-negative euro amount.")
    return amount


def profile() -> dict:
    """Personal data used to fill the German contact message."""
    return {
        "full_name": env("FULL_NAME", ""),
        "email": env("EMAIL", ""),
        "phone": env("PHONE", ""),
        "occupation": env("OCCUPATION", ""),
        "household": env("HOUSEHOLD", ""),
    }


def kleinanzeigen_credentials() -> tuple[str | None, str | None]:
    """(email, password) for auto-login. Password lives only in .env (gitignored)."""
    return env("KLEINANZEIGEN_EMAIL"), env("KLEINANZEIGEN_PASSWORD")
