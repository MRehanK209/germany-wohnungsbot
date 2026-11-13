from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Listing:
    platform: str
    listing_id: str
    url: str
    title: str = ""
    price: str = ""
    rooms: float | None = None
    size: str = ""
    address: str = ""
    raw: dict = field(default_factory=dict)
    published_at: datetime | None = None
    warm_rent_eur: float | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.platform, self.listing_id)
