import html
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from bot.config import parse_max_age_spec, resolve_filters
from bot.dates import json_ld_dates, newest_first, parse_listing_date, publication_date
from bot.main import passes_filters, scan_platform
from bot.models import Listing
from bot.scrapers.immoscout24 import ImmoScout24
from bot.scrapers.kleinanzeigen import Kleinanzeigen
from bot.scrapers.wg_gesucht import WgGesucht
from bot.storage import Store

UTC = timezone.utc
NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)


class DateTests(unittest.TestCase):
    def setUp(self):
        env_patch = patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.cfg = {"filters": {
            "min_rooms": 1, "max_rooms": 2, "min_size_sqm": 28, "max_size_sqm": 50,
            "max_listing_age_days": 7,
        }, "platforms": {"test": {"enabled": True, "auto_contact": False}}}

    def listing(self, ident, published):
        return Listing("test", ident, "https://example.com/" + ident,
                       rooms=1, size="40 m²", published_at=published)

    def test_german_and_iso_dates_use_the_listing_timezone(self):
        for text, expected in [
            ("2026-11-09T12:30:00Z", datetime(2026, 11, 9, 12, 30, tzinfo=UTC)),
            ("2026-11-09T13:30:00+01:00", datetime(2026, 11, 9, 12, 30, tzinfo=UTC)),
            ("09.11.2026, 13:30", datetime(2026, 11, 9, 12, 30, tzinfo=UTC)),
            ("2026-11-09", datetime(2026, 11, 8, 23, tzinfo=UTC)),
            ("09.07.2026", datetime(2026, 7, 8, 22, tzinfo=UTC)),
            ("Heute, 13:30", datetime(2026, 11, 9, 12, 30, tzinfo=UTC)),
            ("Gestern", datetime(2026, 11, 7, 23, tzinfo=UTC)),
        ]:
            with self.subTest(text=text):
                self.assertEqual(parse_listing_date(text, now=NOW), expected)

    def test_epoch_seconds_and_milliseconds(self):
        self.assertEqual(parse_listing_date(NOW.timestamp()), NOW)
        self.assertEqual(parse_listing_date(NOW.timestamp() * 1000), NOW)

    def test_unusable_dates_and_activity_are_not_publication_dates(self):
        for value in (None, "", "31.02.2026", "Online: 2 Std.", "Verfügbar ab 09.11.2026",
                      "Heute, 99:99", float("inf"), float("nan")):
            with self.subTest(value=value):
                self.assertIsNone(parse_listing_date(value, now=NOW))
        soup = BeautifulSoup(
            '<div><time datetime="2026-11-09">Move-in date</time>'
            '<span title="Online:">1 Std.</span></div>', "lxml"
        )
        self.assertIsNone(publication_date(soup, "https://example.com/1", {}))

    def test_age_limit_includes_exactly_seven_days_rejects_future_and_allows_undated(self):
        for published, expected in [
            (NOW, True), (NOW - timedelta(days=1), True),
            (NOW - timedelta(days=7), True),
            (NOW - timedelta(days=7, seconds=1), False),
            (NOW + timedelta(seconds=1), False), (None, True),
        ]:
            with self.subTest(published=published):
                self.assertEqual(
                    passes_filters(self.cfg, self.listing("1", published), now=NOW), expected,
                )

    def test_date_only_at_midnight_is_not_assumed_to_be_newer(self):
        listing = self.listing("1", parse_listing_date("02.11.2026"))
        self.assertFalse(passes_filters(self.cfg, listing, now=NOW))

    def test_age_environment_override_and_disable(self):
        listing = self.listing("1", NOW - timedelta(days=4))
        with patch.dict(os.environ, {"SEARCH_MAX_AGE_DAYS": "3"}):
            self.assertEqual(resolve_filters(self.cfg)["max_listing_age_days"], 3)
            self.assertFalse(passes_filters(self.cfg, listing, now=NOW))
        with patch.dict(os.environ, {"SEARCH_MAX_AGE_DAYS": "0"}):
            self.assertTrue(passes_filters(self.cfg, self.listing("2", None), now=NOW))
        for text in ("-1", "1.5", "nan", "bad"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_max_age_spec(text)

    def test_publication_metadata_matches_each_listing_and_does_not_use_modified_dates(self):
        records = {
            "@type": "CollectionPage", "url": "https://example.com/search",
            "datePublished": "2026-11-09",
            "itemListElement": [
                {"url": "/1", "datePosted": "2026-11-08"},
                {"url": "/2", "datePublished": "2026-10-01", "dateModified": "2026-11-09"},
                {"url": "/3", "dateModified": "2026-11-09"},
            ],
        }
        soup = BeautifulSoup(
            '<script type="application/ld+json">' + json.dumps(records) + "</script>", "lxml",
        )
        dates = json_ld_dates(soup, "https://example.com")
        self.assertEqual(dates["https://example.com/1"], parse_listing_date("2026-11-08"))
        self.assertEqual(dates["https://example.com/2"], parse_listing_date("2026-10-01"))
        self.assertNotIn("https://example.com/3", dates)

    def test_newest_first_is_stable_with_unknown_dates_last(self):
        older = self.listing("older", NOW - timedelta(days=1))
        newest = self.listing("newest", NOW)
        same_date = self.listing("same-date", NOW)
        undated = self.listing("undated", None)
        self.assertEqual(
            newest_first([older, undated, newest, same_date]),
            [newest, same_date, older, undated],
        )

    def test_alerts_are_filtered_and_sorted_before_the_baseline_cap(self):
        listings = [
            self.listing("too-old", NOW - timedelta(days=8)),
            self.listing("middle", NOW - timedelta(days=2)),
            self.listing("undated", None),
            self.listing("newest", NOW - timedelta(hours=1)),
            self.listing("cutoff", NOW - timedelta(days=7)),
        ]
        scraper_cls = Mock(return_value=SimpleNamespace(fetch=lambda browser: listings))
        store = Store(":memory:")
        self.addCleanup(store.db.close)
        tg = Mock()
        self.cfg["first_run_max_per_platform"] = 2
        with patch("bot.main.utc_now", return_value=NOW), patch("bot.main.time.sleep"):
            self.assertTrue(scan_platform(self.cfg, store, tg, None, "test", scraper_cls, False))
        sent = [call.args[0].listing_id for call in tg.send_listing.call_args_list]
        self.assertEqual(sent, ["newest", "middle"])
        self.assertEqual(store.count("test"), len(listings))
        # An old listing stays old even when it was first observed just now.
        self.assertFalse(passes_filters(self.cfg, listings[0], now=NOW))

    def test_existing_database_migrates_without_losing_seen_listings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "listings.db"
            db = sqlite3.connect(path)
            db.execute("""CREATE TABLE listings (
                platform TEXT, listing_id TEXT, url TEXT, title TEXT, price TEXT,
                rooms REAL, size TEXT, address TEXT, first_seen INTEGER,
                contacted INTEGER DEFAULT 0, contact_status TEXT,
                PRIMARY KEY (platform, listing_id))""")
            db.execute("INSERT INTO listings (platform, listing_id, first_seen) VALUES ('test', 'old', 1)")
            db.commit()
            db.close()
            store = Store(path)
            try:
                self.assertTrue(store.is_known("test", "old"))
                self.assertTrue(store.was_notified("test", "old"))
                self.assertEqual(store.db.execute(
                    "SELECT first_seen, published_at FROM listings WHERE listing_id='old'"
                ).fetchone(), (1, None))
                store.add(self.listing("new", NOW))
                self.assertEqual(store.db.execute(
                    "SELECT published_at FROM listings WHERE listing_id='new'"
                ).fetchone()[0], NOW.isoformat())
            finally:
                store.db.close()
            reopened = Store(path)
            try:
                self.assertEqual(reopened.count("test"), 2)
            finally:
                reopened.db.close()

    def test_kleinanzeigen_astro_dates_and_newest_sort(self):
        props = {"resultAds": [1, [
            [0, {"organicAdPreview": [0, {"id": [0, 123], "sortingDate": [0, "02.11.2026"]}]}],
            [0, {"organicAdPreview": [0, {"id": [0, 124], "sortingDate": [0, "09.11.2026"]}]}],
        ]]}
        cards = "".join(
            f'<article data-adid="{ident}" data-href="/s-anzeige/{ident}">'
            f'<h3><a href="/s-anzeige/{ident}">Studio</a></h3></article>'
            for ident in (123, 124)
        )
        source = '<astro-island props="' + html.escape(json.dumps(props), quote=True) + '"></astro-island>' + cards
        scraper = Kleinanzeigen(self.cfg)
        self.assertIn("sortingField=SORTING_DATE", scraper.search_url())
        with patch.object(scraper, "get", return_value=SimpleNamespace(text=source)):
            listings = scraper.fetch()
        self.assertEqual([listing.listing_id for listing in listings], ["124", "123"])
        self.assertEqual(listings[0].published_at, parse_listing_date("09.11.2026"))

    def test_wg_gesucht_uses_date_posted_and_not_online_activity_or_move_in_date(self):
        source = """
          <script type="application/ld+json">
            {"@type":"RealEstateListing","url":"https://www.wg-gesucht.de/123.html",
             "datePosted":"2026-11-08"}
          </script>
          <a class="offer_list_item" data-id="123" href="/123.html">
            <h2>Studio</h2><span class="size-value">40 m²</span>
            <div class="middle-row">01.01.2027</div><span title="Online:">1 Std.</span>
          </a>
          <a class="offer_list_item" data-id="124" href="/124.html">
            <h2>Undated studio</h2><span title="Online:">1 Min.</span>
          </a>
        """
        scraper = WgGesucht(self.cfg)
        self.assertTrue(all("sort_column=0&sort_order=0" in url for url in scraper.search_urls()))
        with patch.object(scraper, "get", return_value=SimpleNamespace(text=source)):
            listings = scraper.fetch()
        self.assertEqual(listings[0].published_at, parse_listing_date("2026-11-08"))
        self.assertIsNone(listings[1].published_at)
        self.assertIn("sorting=2", ImmoScout24(self.cfg).search_url())


if __name__ == "__main__":
    unittest.main()
