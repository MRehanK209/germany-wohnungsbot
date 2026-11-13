import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot.scrapers.kleinanzeigen import Kleinanzeigen
from bot.scrapers.wg_gesucht import WgGesucht


class ScraperTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {"filters": {"min_rooms": 1, "max_rooms": 1}}

    def fetch_html(self, scraper_cls, html):
        scraper = scraper_cls(self.cfg)
        with patch.object(scraper, "get", return_value=SimpleNamespace(text=html)):
            return scraper.fetch()

    def test_current_wg_gesucht_studio_card(self):
        listings = self.fetch_html(WgGesucht, """
            <a class="wgg-list-card offer_list_item" data-id="123"
               href="/1-zimmer-wohnungen-in-Goettingen.123.html">
              <div class="price-row"><span class="card-main-text">550 €</span></div>
              <h2><span class="card-title-text">Studio mit Küche</span></h2>
              <div class="card-details-text"><span>
                1-Zimmer-Wohnung · Göttingen Weende · Beispielstraße 1
              </span></div>
              <span class="size-value">28 m²</span>
            </a>
            <a class="offer_list_item panel-deactivated" data-id="456" href="/456.html">
              <h2>Inactive offer</h2>
            </a>
        """)
        self.assertEqual(len(listings), 1)
        listing = listings[0]
        self.assertEqual(listing.listing_id, "123")
        self.assertEqual(listing.title, "Studio mit Küche")
        self.assertEqual(listing.rooms, 1)
        self.assertEqual(listing.size, "28 m²")
        self.assertEqual(listing.price, "550 €")
        self.assertEqual(listing.address, "Göttingen Weende, Beispielstraße 1")
        self.assertEqual(listing.url, "https://www.wg-gesucht.de/1-zimmer-wohnungen-in-Goettingen.123.html")

    def test_legacy_wg_gesucht_card(self):
        listings = self.fetch_html(WgGesucht, """
            <div class="wgg_card offer_list_item" data-id="123">
              <h2 class="truncate_title"><a href="/123.html">Studio mit Küche</a></h2>
              <div class="col-xs-11"><span>1-Zimmer-Wohnung | Göttingen Weende</span></div>
              <div class="row noprint middle">
                <div class="col-xs-3"><b>550 €</b></div>
                <div class="col-xs-3 text-right"><b>28 m²</b></div>
              </div>
            </div>
        """)
        self.assertEqual(len(listings), 1)
        self.assertEqual((listings[0].rooms, listings[0].size, listings[0].price), (1, "28 m²", "550 €"))

    def test_current_kleinanzeigen_card(self):
        listings = self.fetch_html(Kleinanzeigen, """
            <article data-adid="123" data-href="/s-anzeige/studio/123">
              <div><svg data-title="locationOutline"></svg><span>37073 Göttingen</span></div>
              <h3><a href="/s-anzeige/studio/123">Studio mit Küche</a></h3>
              <p class="font-strong text-onSurfaceSubdued">28,5 m² · 1 Zi.</p>
              <p class="text-title3">550 €</p>
            </article>
            <article data-adid="456" data-href="/s-anzeige/top-ad/456">
              <div class="bg-accent">TOP</div>
            </article>
        """)
        self.assertEqual(len(listings), 1)
        listing = listings[0]
        self.assertEqual(listing.title, "Studio mit Küche")
        self.assertEqual(listing.rooms, 1)
        self.assertEqual(listing.size, "28,5 m²")
        self.assertEqual(listing.price, "550 €")
        self.assertEqual(listing.address, "37073 Göttingen")
        self.assertEqual(listing.url, "https://www.kleinanzeigen.de/s-anzeige/studio/123")

    def test_legacy_kleinanzeigen_card(self):
        listings = self.fetch_html(Kleinanzeigen, """
            <article class="aditem" data-adid="123" data-href="/s-anzeige/studio/123">
              <div class="aditem-main--top--left">37073 Göttingen</div>
              <h2><a href="/s-anzeige/studio/123">Studio mit Küche</a></h2>
              <p class="aditem-main--middle--tags">28 m² · 1 Zi.</p>
              <p class="aditem-main--middle--price-shipping--price">550 €</p>
            </article>
        """)
        self.assertEqual(len(listings), 1)
        self.assertEqual((listings[0].rooms, listings[0].size, listings[0].price), (1, "28 m²", "550 €"))


if __name__ == "__main__":
    unittest.main()


class PlatformFixTests(unittest.TestCase):
    def test_vonovia_sends_the_search_token_header(self):
        from bot.scrapers.vonovia import TOKEN_URL, Vonovia

        calls = []

        def fake_get(url, **kw):
            calls.append((url, kw))
            if url == TOKEN_URL:
                return SimpleNamespace(json=lambda: {"token": "abc", "ttl": 900})
            return SimpleNamespace(json=lambda: {"results": [{
                "wrk_id": "42", "titel": "2-Zimmer", "preis": 520, "groesse": 45,
                "anzahl_zimmer": 2, "slug": "zwei-zimmer-42", "strasse": "Weg 1 ",
                "plz": "37081", "ort": "Göttingen",
            }]})

        scraper = Vonovia({"filters": {}})
        with patch.object(scraper, "get", side_effect=fake_get):
            listings = scraper.fetch()
        self.assertEqual(calls[1][1]["headers"]["X-VON-Search-Token"], "abc")
        self.assertEqual(len(listings), 1)
        listing = listings[0]
        self.assertEqual((listing.rooms, listing.size, listing.price), (2.0, "45 m²", "520 €"))
        self.assertEqual(listing.address, "Weg 1, 37081 Göttingen")

    def test_vonovia_without_token_fails_loudly(self):
        from bot.scrapers.vonovia import Vonovia

        scraper = Vonovia({"filters": {}})
        with patch.object(scraper, "get", return_value=SimpleNamespace(json=lambda: {})):
            with self.assertRaises(RuntimeError):
                scraper.fetch()

    def test_base_get_merges_extra_headers(self):
        from bot.scrapers.base import HEADERS, BaseScraper

        with patch("bot.scrapers.base.httpx.get") as get:
            BaseScraper({}).get("https://example.com", headers={"X-Test": "1"})
        sent = get.call_args.kwargs["headers"]
        self.assertEqual(sent["X-Test"], "1")
        self.assertEqual(sent["User-Agent"], HEADERS["User-Agent"])

    def test_immoscout_url_includes_rooms_and_area(self):
        from bot.scrapers.immoscout24 import ImmoScout24

        url = ImmoScout24({"filters": {"min_rooms": 1, "max_rooms": 2,
                                       "min_size_sqm": 28, "max_size_sqm": 50}}).search_url()
        self.assertIn("numberofrooms=1.0-2.0", url)
        self.assertIn("livingspace=28.0-50.0", url)
        self.assertTrue(url.endswith("&sorting=2"))
        url = ImmoScout24({"filters": {"min_rooms": 2, "max_rooms": 99}}).search_url()
        self.assertIn("numberofrooms=2.0-&", url)
        self.assertNotIn("livingspace", url)

    def test_repeated_platform_failures_alert_once_and_recovery_is_reported(self):
        from bot.main import FAILURE_ALERT_AFTER, track_platform_health

        tg = SimpleNamespace(sent=[])
        tg.send = tg.sent.append
        fails = {}
        for _ in range(FAILURE_ALERT_AFTER + 3):
            track_platform_health(tg, "immoscout24", False, fails)
        self.assertEqual(len(tg.sent), 1)
        self.assertIn("login.sh immoscout24", tg.sent[0])
        track_platform_health(tg, "immoscout24", True, fails)
        self.assertEqual(len(tg.sent), 2)
        self.assertIn("working again", tg.sent[1])
        # A single blip that recovers stays silent.
        track_platform_health(tg, "vonovia", False, fails)
        track_platform_health(tg, "vonovia", True, fails)
        self.assertEqual(len(tg.sent), 2)
