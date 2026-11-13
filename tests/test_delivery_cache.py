import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bot.main import scan_platform
from bot.models import Listing
from bot.storage import Store
from bot.telegram import Telegram

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)


class DeliveryCacheTests(unittest.TestCase):
    def setUp(self):
        env_patch = patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "listings.db"
        self.cfg = {"filters": {
            "min_rooms": 1, "max_rooms": 2, "min_size_sqm": 28, "max_size_sqm": 50,
            "max_listing_age_days": 7, "max_warm_rent_eur": 600,
        }, "platforms": {"test": {"enabled": True, "auto_contact": False}}}

    def listing(self, ident="1", warm=580):
        return Listing("test", ident, "https://example.com/" + ident, rooms=1,
                       size="40 m²", price="450 €", published_at=NOW, warm_rent_eur=warm)

    def scan(self, store, tg, listings=(), enrich=None, fetch_error=None, allow_contact=False):
        scraper = SimpleNamespace(
            fetch=Mock(return_value=list(listings), side_effect=fetch_error),
            enrich_rent=enrich or Mock(),
        )
        with patch("bot.main.utc_now", return_value=NOW), patch("bot.main.time.sleep"):
            return scan_platform(self.cfg, store, tg, object(), "test",
                                 lambda cfg: scraper, allow_contact)

    def test_successful_delivery_is_not_repeated_after_restart(self):
        store = Store(self.path)
        tg = Mock()
        self.scan(store, tg, [self.listing()])
        self.assertTrue(store.was_notified("test", "1"))
        store.db.close()
        restarted = Store(self.path)
        try:
            self.scan(restarted, tg, [self.listing(), self.listing("2")])
            sent = [call.args[0].listing_id for call in tg.send_listing.call_args_list]
            self.assertEqual(sent, ["1", "2"])
            self.assertEqual(restarted.pending_notifications("test"), [])
        finally:
            restarted.db.close()

    def test_failed_send_retries_from_cache_even_after_leaving_the_search_page(self):
        store = Store(self.path)
        tg = Mock()
        tg.send_listing.side_effect = RuntimeError("Telegram unavailable")
        with self.assertLogs("wohnungsbot", level="ERROR"):
            self.scan(store, tg, [self.listing()])
        self.assertFalse(store.was_notified("test", "1"))
        self.assertEqual(len(store.pending_notifications("test")), 1)
        store.db.close()
        restarted = Store(self.path)
        try:
            tg.send_listing.side_effect = None
            self.scan(restarted, tg, [])
            self.assertTrue(restarted.was_notified("test", "1"))
            self.scan(restarted, tg, [self.listing()])
            self.assertEqual(tg.send_listing.call_count, 2)  # failed attempt, then success
        finally:
            restarted.db.close()

    def test_cached_retry_works_during_a_scraper_outage(self):
        store = Store(":memory:")
        self.addCleanup(store.db.close)
        store.add(self.listing())
        store.mark_notification_pending("test", "1")
        tg = Mock()
        with self.assertLogs("wohnungsbot", level="WARNING"):
            self.assertFalse(self.scan(store, tg, fetch_error=RuntimeError("site down")))
        tg.send_listing.assert_called_once()
        self.assertTrue(store.was_notified("test", "1"))

    def test_warm_rent_lookup_is_cached_for_failed_notification_retries(self):
        store = Store(":memory:")
        self.addCleanup(store.db.close)
        tg = Mock()
        tg.send_listing.side_effect = RuntimeError("Telegram unavailable")
        enrich = Mock(side_effect=lambda listing, browser: setattr(listing, "warm_rent_eur", 580))
        with self.assertLogs("wohnungsbot", level="ERROR"):
            self.scan(store, tg, [self.listing(warm=None)], enrich)
        tg.send_listing.side_effect = None
        incomplete_live_result = self.listing(warm=None)
        incomplete_live_result.published_at = None
        self.scan(store, tg, [incomplete_live_result], enrich)
        self.scan(store, tg, [self.listing(warm=None)], enrich)
        self.assertEqual(enrich.call_count, 1)
        self.assertTrue(store.was_notified("test", "1"))

    def test_temporary_warm_rent_lookup_failure_can_retry(self):
        store = Store(":memory:")
        self.addCleanup(store.db.close)
        tg = Mock()
        with self.assertLogs("wohnungsbot", level="WARNING"):
            self.scan(store, tg, [self.listing(warm=None)],
                      enrich=Mock(side_effect=RuntimeError("network error")))
        tg.send_listing.assert_not_called()
        self.assertEqual(len(store.pending_notifications("test")), 1)
        self.scan(store, tg, [self.listing(warm=None)],
                  enrich=Mock(side_effect=lambda listing, browser: setattr(listing, "warm_rent_eur", 580)))
        tg.send_listing.assert_called_once()

    def test_pending_old_listings_are_still_excluded(self):
        store = Store(":memory:")
        self.addCleanup(store.db.close)
        listing = self.listing()
        listing.published_at = NOW - timedelta(days=8)
        store.add(listing)
        store.mark_notification_pending("test", "1")
        tg = Mock()
        self.scan(store, tg)
        tg.send_listing.assert_not_called()

    def test_metadata_updates_preserve_delivery_state_and_first_seen(self):
        store = Store(":memory:")
        self.addCleanup(store.db.close)
        listing = self.listing()
        store.add(listing)
        store.mark_notified("test", "1")
        before = store.db.execute("SELECT first_seen FROM listings").fetchone()[0]
        listing.title = "Updated title"
        store.add(listing)
        self.assertTrue(store.was_notified("test", "1"))
        self.assertEqual(store.db.execute("SELECT first_seen FROM listings").fetchone()[0], before)

    def test_auto_contact_is_not_repeated_when_only_telegram_failed(self):
        store = Store(":memory:")
        self.addCleanup(store.db.close)
        store.add(self.listing("seed"))
        self.cfg["platforms"]["test"]["auto_contact"] = True
        tg = Mock()
        tg.send_listing.side_effect = RuntimeError("Telegram unavailable")
        with patch("bot.main.try_contact", return_value="sent") as contact:
            with self.assertLogs("wohnungsbot", level="ERROR"):
                self.scan(store, tg, [self.listing()], allow_contact=True)
            tg.send_listing.side_effect = None
            self.scan(store, tg, [self.listing()], allow_contact=True)
            contact.assert_called_once()

    def test_telegram_must_confirm_delivery_even_with_http_success(self):
        store = Store(":memory:")
        self.addCleanup(store.db.close)
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "1"}):
            tg = Telegram()
        response = Mock()
        response.json.return_value = {"ok": False, "description": "rejected"}
        with patch("bot.telegram.httpx.post", return_value=response):
            with self.assertLogs("wohnungsbot", level="ERROR"):
                self.scan(store, tg, [self.listing()])
            self.assertFalse(store.was_notified("test", "1"))
            response.json.return_value = {"ok": True, "result": {"message_id": 123}}
            self.scan(store, tg)
        self.assertTrue(store.was_notified("test", "1"))


if __name__ == "__main__":
    unittest.main()
