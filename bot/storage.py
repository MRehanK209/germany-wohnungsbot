import sqlite3
import time

from .config import DATA_DIR
from .dates import parse_listing_date
from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    platform       TEXT NOT NULL,
    listing_id     TEXT NOT NULL,
    url            TEXT,
    title          TEXT,
    price          TEXT,
    rooms          REAL,
    size           TEXT,
    address        TEXT,
    published_at   TEXT,
    warm_rent_eur  REAL,
    telegram_sent_at INTEGER,
    notification_pending INTEGER DEFAULT 0,
    first_seen     INTEGER,
    contacted      INTEGER DEFAULT 0,
    contact_status TEXT,
    PRIMARY KEY (platform, listing_id)
);
CREATE TABLE IF NOT EXISTS contact_log (
    ts INTEGER NOT NULL
);
"""


class Store:
    def __init__(self, path=None):
        DATA_DIR.mkdir(exist_ok=True)
        self.db = sqlite3.connect(path or DATA_DIR / "listings.db")
        self.db.executescript(SCHEMA)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(listings)")}
        if "published_at" not in columns:
            self.db.execute("ALTER TABLE listings ADD COLUMN published_at TEXT")
        if "warm_rent_eur" not in columns:
            self.db.execute("ALTER TABLE listings ADD COLUMN warm_rent_eur REAL")
        if "telegram_sent_at" not in columns:
            self.db.execute("ALTER TABLE listings ADD COLUMN telegram_sent_at INTEGER")
            # Old versions recorded seen IDs without delivery state. Preserve
            # those IDs as handled so an upgrade cannot flood the chat.
            self.db.execute(
                "UPDATE listings SET telegram_sent_at=COALESCE(first_seen, ?)",
                (int(time.time()),),
            )
        if "notification_pending" not in columns:
            self.db.execute(
                "ALTER TABLE listings ADD COLUMN notification_pending INTEGER DEFAULT 0"
            )
        self.db.commit()

    def is_known(self, platform: str, listing_id: str) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM listings WHERE platform=? AND listing_id=?",
            (platform, listing_id),
        ).fetchone()
        return row is not None

    def count(self, platform: str) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM listings WHERE platform=?", (platform,)
        ).fetchone()[0]

    def add(self, l: Listing):
        self.db.execute(
            "INSERT INTO listings "
            "(platform, listing_id, url, title, price, rooms, size, address, published_at, warm_rent_eur, first_seen) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(platform, listing_id) DO UPDATE SET "
            "url=excluded.url, title=excluded.title, price=excluded.price, "
            "rooms=excluded.rooms, size=excluded.size, address=excluded.address, "
            "published_at=excluded.published_at, warm_rent_eur=excluded.warm_rent_eur",
            (l.platform, l.listing_id, l.url, l.title, l.price, l.rooms,
             l.size, l.address, l.published_at.isoformat() if l.published_at else None,
             l.warm_rent_eur, int(time.time())),
        )
        self.db.commit()

    def was_notified(self, platform: str, listing_id: str) -> bool:
        row = self.db.execute(
            "SELECT telegram_sent_at FROM listings WHERE platform=? AND listing_id=?",
            (platform, listing_id),
        ).fetchone()
        return row is not None and row[0] is not None

    def mark_notification_pending(self, platform: str, listing_id: str):
        self.db.execute(
            "UPDATE listings SET notification_pending=1 "
            "WHERE platform=? AND listing_id=? AND telegram_sent_at IS NULL",
            (platform, listing_id),
        )
        self.db.commit()

    def mark_notified(self, platform: str, listing_id: str):
        self.db.execute(
            "UPDATE listings SET telegram_sent_at=?, notification_pending=0 "
            "WHERE platform=? AND listing_id=?",
            (int(time.time()), platform, listing_id),
        )
        self.db.commit()

    def pending_notifications(self, platform: str) -> list[Listing]:
        rows = self.db.execute(
            "SELECT platform, listing_id, url, title, price, rooms, size, address, "
            "published_at, warm_rent_eur FROM listings "
            "WHERE platform=? AND notification_pending=1 AND telegram_sent_at IS NULL",
            (platform,),
        ).fetchall()
        return [
            Listing(platform=row[0], listing_id=row[1], url=row[2], title=row[3] or "",
                    price=row[4] or "", rooms=row[5], size=row[6] or "", address=row[7] or "",
                    published_at=parse_listing_date(row[8]), warm_rent_eur=row[9])
            for row in rows
        ]

    def mark_contacted(self, platform: str, listing_id: str, status: str):
        self.db.execute(
            "UPDATE listings SET contacted=1, contact_status=? "
            "WHERE platform=? AND listing_id=?",
            (status, platform, listing_id),
        )
        self.db.execute("INSERT INTO contact_log (ts) VALUES (?)", (int(time.time()),))
        self.db.commit()

    def contacts_last_hour(self) -> int:
        return self.db.execute(
            "SELECT COUNT(*) FROM contact_log WHERE ts > ?", (int(time.time()) - 3600,)
        ).fetchone()[0]
