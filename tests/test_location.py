import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bot import location
from bot.config import load_config
from bot.location import LocationError
from bot.main import platform_active, prepare_platforms
from bot.scrapers.immoscout24 import ImmoScout24
from bot.scrapers.immowelt import Immowelt
from bot.scrapers.kleinanzeigen import Kleinanzeigen
from bot.scrapers.vonovia import Vonovia
from bot.scrapers.wg_gesucht import WgGesucht

FILTERS = {"min_rooms": 1, "max_rooms": 99}


def cfg_for(city, **platforms):
    return {"city": city, "filters": dict(FILTERS),
            "platforms": {name: {"enabled": on} for name, on in platforms.items()}}


def json_response(payload):
    return SimpleNamespace(json=lambda: payload)


class LocationTests(unittest.TestCase):
    def setUp(self):
        env_patch = patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        location._cache.clear()
        self.addCleanup(location._cache.clear)

    def test_city_defaults_to_goettingen_and_env_overrides(self):
        self.assertEqual(load_config()["city"], "Göttingen")
        with patch.dict(os.environ, {"SEARCH_CITY": "  Berlin "}):
            self.assertEqual(load_config()["city"], "Berlin")

    def test_slugify(self):
        self.assertEqual(location.slugify("Göttingen"), "goettingen")
        self.assertEqual(location.slugify("Frankfurt am Main"), "frankfurt-am-main")
        self.assertEqual(location.slugify("Düsseldorf"), "duesseldorf")
        self.assertTrue(location.is_default_city("goettingen"))
        self.assertFalse(location.is_default_city("Berlin"))

    def test_goettingen_uses_built_in_ids_without_network(self):
        cfg = cfg_for("Göttingen")
        get = Mock(side_effect=AssertionError("no lookup expected"))
        for scraper_cls in (Kleinanzeigen, WgGesucht, Immowelt):
            scraper = scraper_cls(cfg)
            scraper.get = get
            scraper.check_location()
        self.assertIn("c203l3130+", Kleinanzeigen(cfg).search_url())
        self.assertIn(".49.2.1.0.html", WgGesucht(cfg).search_urls()[-1])
        self.assertIn("/goettingen/wohnung-mieten?", ImmoScout24(cfg).search_url())

    def test_kleinanzeigen_resolves_city_not_district(self):
        payload = {"_0": "Deutschland", "_3464": "Pankow - Berlin", "_3331": "Berlin"}
        scraper = Kleinanzeigen(cfg_for("Berlin"))
        with patch.object(scraper, "get", return_value=json_response(payload)) as get:
            url = scraper.search_url()
            scraper.search_url()
        self.assertIn("/s-wohnung-mieten/berlin/anzeige:angebote/c203l3331+", url)
        self.assertEqual(get.call_count, 1)  # cached

    def test_kleinanzeigen_accepts_city_with_state_suffix(self):
        payload = {"_0": "Deutschland", "_6411": "München - Bayern"}
        scraper = Kleinanzeigen(cfg_for("München"))
        with patch.object(scraper, "get", return_value=json_response(payload)):
            self.assertIn("c203l6411+", scraper.search_url())

    def test_kleinanzeigen_unknown_city(self):
        scraper = Kleinanzeigen(cfg_for("Atlantis"))
        with patch.object(scraper, "get", return_value=json_response({"_0": "Deutschland"})):
            with self.assertRaises(LocationError):
                scraper.check_location()

    def test_wg_gesucht_picks_the_exact_german_city(self):
        payload = {"_embedded": {"cities": [
            {"city_id": "5038", "city_name": "Berlingen", "country_code": "de"},
            {"city_id": "8", "city_name": "Berlin", "country_code": "de"},
        ]}}
        scraper = WgGesucht(cfg_for("Berlin"))
        with patch.object(scraper, "get", return_value=json_response(payload)):
            urls = scraper.search_urls()
        self.assertEqual([u.split("?")[0].rsplit("/", 1)[1] for u in urls],
                         ["1-zimmer-wohnungen-in-Berlin.8.1.1.0.html", "wohnungen-in-Berlin.8.2.1.0.html"])

    def test_wg_gesucht_unknown_city(self):
        scraper = WgGesucht(cfg_for("Atlantis"))
        with patch.object(scraper, "get", return_value=json_response({"_embedded": {"cities": []}})):
            with self.assertRaises(LocationError):
                scraper.check_location()

    def test_immowelt_follows_the_legacy_redirect(self):
        final = "https://www.immowelt.de/suche/mieten/wohnung/berlin/berlin-10115/ad08de8634?x=1"
        scraper = Immowelt(cfg_for("Berlin"))
        with patch.object(scraper, "get", return_value=SimpleNamespace(url=final)) as get:
            url = scraper.search_url()
        self.assertEqual(url, final.split("?")[0])
        self.assertIn("/liste/berlin/wohnungen/mieten", get.call_args.args[0])

    def test_immowelt_unknown_city_and_override(self):
        scraper = Immowelt(cfg_for("Atlantis"))
        gone = SimpleNamespace(url="https://www.immowelt.de/suche/atlantis/wohnungen/mieten")
        with patch.object(scraper, "get", return_value=gone):
            with self.assertRaises(LocationError):
                scraper.check_location()
        pasted = "https://www.immowelt.de/suche/mieten/wohnung/x/y-12345/ad08de1?sort=date"
        with patch.dict(os.environ, {"IMMOWELT_SEARCH_URL": pasted}):
            self.assertEqual(Immowelt(cfg_for("Atlantis")).search_url(), pasted.split("?")[0])

    def test_immoscout_needs_a_pasted_url_outside_goettingen(self):
        with self.assertRaises(LocationError):
            ImmoScout24(cfg_for("Berlin")).search_url()
        pasted = "https://www.immobilienscout24.de/Suche/de/berlin/berlin/wohnung-mieten?enteredFrom=x"
        with patch.dict(os.environ, {"IMMOSCOUT24_SEARCH_URL": pasted}):
            url = ImmoScout24(cfg_for("Berlin")).search_url()
        self.assertTrue(url.startswith("https://www.immobilienscout24.de/Suche/de/berlin/berlin/wohnung-mieten?numberofrooms="))

    def test_vonovia_searches_the_configured_city(self):
        scraper = Vonovia(cfg_for("München"))
        urls = []

        def fake_get(url, **kw):
            urls.append(url)
            return json_response({"token": "t"} if "search-token" in url else {"results": []})

        with patch.object(scraper, "get", side_effect=fake_get):
            scraper.fetch()
        self.assertIn("city=M%C3%BCnchen", urls[1])

    def test_prepare_platforms_skips_local_coops_and_unknown_cities(self):
        cfg = cfg_for("Berlin", kleinanzeigen=True, immowelt=True, volksheimstaette=True,
                      wg_eg=True, immoscout24=True, vonovia=True, wg_gesucht=False)
        tg = Mock()
        with patch.object(Kleinanzeigen, "check_location"), \
                patch.object(Immowelt, "check_location", side_effect=ConnectionError("offline")):
            active = prepare_platforms(cfg, tg)
        # Local co-ops are Göttingen-only; ImmoScout24 has no URL for Berlin;
        # a network error keeps the platform for a retry during scans.
        self.assertEqual(active, ["kleinanzeigen", "immowelt", "vonovia"])
        self.assertFalse(platform_active(cfg, "wg_eg"))
        tg.send.assert_called_once()
        self.assertIn("ImmoScout24", tg.send.call_args.args[0])

    def test_prepare_platforms_keeps_everything_for_goettingen(self):
        cfg = cfg_for("Göttingen", kleinanzeigen=True, volksheimstaette=True, wg_eg=True, vonovia=True)
        tg = Mock()
        self.assertEqual(prepare_platforms(cfg, tg),
                         ["kleinanzeigen", "volksheimstaette", "wg_eg", "vonovia"])
        tg.send.assert_not_called()


class CityChangeBaselineTests(unittest.TestCase):
    def setUp(self):
        env_patch = patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def test_remember_city_detects_a_change(self):
        import tempfile
        from pathlib import Path
        from bot.main import remember_city

        with tempfile.TemporaryDirectory() as d, patch("bot.main.DATA_DIR", Path(d)):
            self.assertFalse(remember_city("Göttingen"))  # existing install, default city
            self.assertFalse(remember_city("goettingen"))
            self.assertTrue(remember_city("Berlin"))
            self.assertFalse(remember_city("Berlin"))

    def test_first_scan_after_city_change_is_capped_like_a_first_run(self):
        from bot.dates import utc_now
        from bot.main import scan_platform
        from bot.models import Listing
        from bot.storage import Store

        store = Store(":memory:")
        self.addCleanup(store.db.close)
        store.add(Listing("test", "old-goettingen-ad", "https://example.com/old"))
        now = utc_now()

        def listings(prefix):
            return [Listing("test", f"{prefix}{i}", f"https://example.com/{prefix}{i}", rooms=1,
                            size="40 m²", price="450 €", warm_rent_eur=450, published_at=now)
                    for i in range(5)]

        cfg = {"city": "Berlin", "city_changed": True, "first_run_max_per_platform": 2,
               "filters": {"min_rooms": 1, "max_rooms": 99, "max_warm_rent_eur": 600},
               "platforms": {}}
        tg = Mock()
        batches = iter([listings("a"), listings("b")])
        scraper_cls = Mock(side_effect=lambda cfg: SimpleNamespace(
            fetch=lambda browser: next(batches), enrich_rent=Mock()))
        with patch("bot.main.time.sleep"):
            scan_platform(cfg, store, tg, None, "test", scraper_cls, False)
            self.assertEqual(tg.send_listing.call_count, 2)  # capped backlog
            scan_platform(cfg, store, tg, None, "test", scraper_cls, False)
        self.assertEqual(tg.send_listing.call_count, 7)  # afterwards: every new ad
