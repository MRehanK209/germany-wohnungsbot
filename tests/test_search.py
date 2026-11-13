import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from bot.config import load_config, parse_size_limit_spec, resolve_filters
from bot.main import passes_filters
from bot.dates import utc_now
from bot.models import Listing
from bot.scrapers.kleinanzeigen import Kleinanzeigen
from bot.scrapers.wg_gesucht import WgGesucht
from bot.wizard import main as run_wizard


class SearchTests(unittest.TestCase):
    def setUp(self):
        env_patch = patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.cfg = {"filters": {
            "min_rooms": 1, "max_rooms": 1, "min_size_sqm": 28, "max_size_sqm": 50,
        }}

    def test_area_range_and_room_count(self):
        for rooms, size, expected in [
            (1, "27,9 m²", False),
            (1, "28 m²", True),
            (1, "28,50 m²", True),
            (1, "28.50 m2", True),
            (1, "ca. 29 qm", True),
            (1, "28", True),
            (1, 28.5, True),
            (1, "49,9 m²", True),
            (1, "50 m²", True),
            (1, "50,01 m²", False),
            (1, "50.5 m2", False),
            (1, 51, False),
            (1, "", False),
            (1, "auf Anfrage", False),
            (1, None, False),
            (1, "-28 m²", False),
            (1, "0 m²", False),
            (1, float("nan"), False),
            (1, float("inf"), False),
            (2, "40 m²", False),
        ]:
            with self.subTest(rooms=rooms, size=size):
                listing = Listing("test", "1", "https://example.com", rooms=rooms, size=size)
                self.assertEqual(passes_filters(self.cfg, listing), expected)

    def test_area_filter_can_be_disabled(self):
        listing = Listing("test", "1", "https://example.com", rooms=1)
        for limit in (None, 0):
            self.cfg["filters"]["min_size_sqm"] = limit
            self.cfg["filters"]["max_size_sqm"] = limit
            self.assertTrue(passes_filters(self.cfg, listing))

    def test_area_limits_can_be_used_independently(self):
        for minimum, maximum, size, expected in [
            (28, None, "27,9 m²", False),
            (28, None, "51 m²", True),
            (None, 50, "20 m²", True),
            (None, 50, "51 m²", False),
        ]:
            with self.subTest(minimum=minimum, maximum=maximum, size=size):
                self.cfg["filters"]["min_size_sqm"] = minimum
                self.cfg["filters"]["max_size_sqm"] = maximum
                listing = Listing("test", "1", "https://example.com", rooms=1, size=size)
                self.assertEqual(passes_filters(self.cfg, listing), expected)

    def test_environment_overrides_search_preferences(self):
        with patch.dict(os.environ, {
            "SEARCH_ROOMS": "1-2",
            "SEARCH_MIN_SIZE_SQM": "30,5",
            "SEARCH_MAX_SIZE_SQM": "45,5",
            "SEARCH_POSTAL_CODES": "37073, 37075",
        }):
            filters = resolve_filters(self.cfg)
            self.assertEqual((filters["min_rooms"], filters["max_rooms"]), (1, 2))
            self.assertEqual(filters["min_size_sqm"], 30.5)
            self.assertEqual(filters["max_size_sqm"], 45.5)
            self.assertEqual(filters["postal_codes"], ["37073", "37075"])
            for size in ("30 m²", "46 m²"):
                listing = Listing("test", "1", "https://example.com", rooms=1, size=size)
                self.assertFalse(passes_filters(self.cfg, listing))
        self.assertEqual(self.cfg["filters"]["min_size_sqm"], 28)
        self.assertEqual(self.cfg["filters"]["max_size_sqm"], 50)

    def test_inverted_area_range_is_rejected(self):
        with patch.dict(os.environ, {"SEARCH_MAX_SIZE_SQM": "20"}):
            with self.assertRaisesRegex(ValueError, "Minimum area cannot exceed maximum area"):
                resolve_filters(self.cfg)

    def test_invalid_area_limit_is_rejected(self):
        for spec in ("-1", "nan", "inf", "not a number"):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                parse_size_limit_spec(spec)

    def test_default_search_is_for_one_to_two_rooms(self):
        with patch.dict(os.environ, {
            "SEARCH_ROOMS": "1-2", "SEARCH_MIN_SIZE_SQM": "28", "SEARCH_MAX_SIZE_SQM": "50",
        }):
            cfg = load_config()
        self.assertEqual(cfg["filters"]["min_rooms"], 1)
        self.assertEqual(cfg["filters"]["max_rooms"], 2)
        self.assertEqual(cfg["filters"]["max_size_sqm"], 50)
        self.assertEqual(cfg["filters"]["min_size_sqm"], 28)
        url = Kleinanzeigen(cfg).search_url()
        self.assertIn("zimmer_d:1%2C2", url)
        self.assertIn("qm_d:28%2C50", url)
        self.assertIn("/anzeige:angebote/", url)
        for rooms, expected in ((1, True), (1.5, True), (2, True), (3, False)):
            with self.subTest(rooms=rooms):
                listing = Listing("test", "1", "https://example.com", rooms=rooms,
                                  size="28 m²", published_at=utc_now(), warm_rent_eur=550)
                self.assertEqual(passes_filters(cfg, listing), expected)

    def test_kleinanzeigen_open_room_range_and_no_area_maximum(self):
        cfg = {"filters": {"min_rooms": 1, "max_rooms": 99, "max_size_sqm": 0}}
        url = Kleinanzeigen(cfg).search_url()
        self.assertTrue(urlsplit(url).path.endswith("zimmer_d:1%2C"))
        self.assertEqual(urlsplit(url).query, "sortingField=SORTING_DATE")
        self.assertNotIn("qm_d:", url)

    def test_kleinanzeigen_area_limits_can_be_used_independently(self):
        for minimum, maximum, expected in [(28, None, "28%2C"), (None, 50, "%2C50")]:
            with self.subTest(minimum=minimum, maximum=maximum):
                cfg = {"filters": {
                    "min_rooms": 1, "max_rooms": 2,
                    "min_size_sqm": minimum, "max_size_sqm": maximum,
                }}
                self.assertTrue(urlsplit(Kleinanzeigen(cfg).search_url()).path.endswith(f"qm_d:{expected}"))

    def test_wg_gesucht_selects_apartment_categories(self):
        studio = "https://www.wg-gesucht.de/1-zimmer-wohnungen-in-Goettingen.49.1.1.0.html"
        apartment = "https://www.wg-gesucht.de/wohnungen-in-Goettingen.49.2.1.0.html"
        for lo, hi, expected in [
            (1, 1, [studio]), (3, 3.5, [apartment]), (1, 2, [studio, apartment]),
            (1, 3, [studio, apartment]),
        ]:
            with self.subTest(lo=lo, hi=hi):
                cfg = {"filters": {"min_rooms": lo, "max_rooms": hi}}
                self.assertEqual(WgGesucht(cfg).search_urls(),
                                 [url + "?sort_column=0&sort_order=0" for url in expected])

    def test_wizard_keeps_one_to_two_room_defaults(self):
        self._check_wizard(["", "", "", "", ""], "1-2", "28", "50")

    def test_wizard_saves_the_chosen_city(self):
        self._check_wizard(["", "", "", "", ""], "1-2", "28", "50", city="Berlin")

    def test_wizard_reprompts_for_invalid_filters(self):
        self._check_wizard(
            ["bad", "2-1", "1", "-1", "nan", "28,5", "-1", "nan", "20", "45,5",
             "-1", "1.5", "7", "-1", "nan", "600,50"],
            "1", "28.5", "45.5", expected_rent="600.5",
        )

    def _check_wizard(self, filter_answers, expected_rooms, expected_min_size, expected_max_size,
                      expected_rent="600", city=""):
        answers = ["test-token", city, *filter_answers, "", "", "", "", "", ""]
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("bot.wizard.ROOT", Path(directory)),
                patch("bot.wizard.load_config", return_value={"filters": {
                    "min_rooms": 1, "max_rooms": 2, "min_size_sqm": 28,
                    "max_size_sqm": 50, "max_listing_age_days": 7, "max_warm_rent_eur": 600,
                }}),
                patch("bot.wizard.detect_chat_id", return_value="123"),
                patch("bot.wizard.httpx.post"),
                patch("builtins.input", side_effect=answers),
                patch("builtins.print"),
            ):
                run_wizard()
            saved = (Path(directory) / ".env").read_text()
        self.assertIn(f"SEARCH_CITY={city or 'Göttingen'}\n", saved)
        self.assertIn(f"SEARCH_ROOMS={expected_rooms}\n", saved)
        self.assertIn(f"SEARCH_MIN_SIZE_SQM={expected_min_size}\n", saved)
        self.assertIn(f"SEARCH_MAX_SIZE_SQM={expected_max_size}\n", saved)
        self.assertIn("SEARCH_MAX_AGE_DAYS=7\n", saved)
        self.assertIn(f"SEARCH_MAX_WARM_RENT_EUR={expected_rent}\n", saved)


if __name__ == "__main__":
    unittest.main()
