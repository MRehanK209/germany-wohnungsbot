import os
import unittest
from unittest.mock import patch

from bot.config import parse_rent_limit_spec, resolve_filters
from bot.main import passes_filters
from bot.models import Listing
from bot.money import parse_euro_amount
from bot.rent import warm_rent_from_html
from bot.scrapers import ALL_SCRAPERS


class RentTests(unittest.TestCase):
    def setUp(self):
        env_patch = patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.cfg = {"filters": {"min_rooms": 1, "max_rooms": 2, "max_warm_rent_eur": 600}}

    def test_currency_formats_preserve_cents(self):
        for value, expected in [
            ("600 €", 600), ("600,50 €", 600.5), ("600.50 EUR", 600.5),
            ("1.200,50 €", 1200.5), ("1,200.50 €", 1200.5),
            ("1 200,50 €", 1200.5), ("1\u202f200,50 €", 1200.5),
            ("600,- €", 600), ("€ 600", 600), ("600 € VB", 600),
            (600.5, 600.5), ("0", 0),
        ]:
            with self.subTest(value=value):
                self.assertEqual(parse_euro_amount(value), expected)
        for value in (None, "", "VB", "auf Anfrage", "-600", float("nan"),
                      float("inf"), "600 € + 50 €", "10 €/m²", True):
            with self.subTest(value=value):
                self.assertIsNone(parse_euro_amount(value))

    def test_warm_ceiling_is_inclusive_across_every_platform(self):
        for platform in ALL_SCRAPERS:
            for warm, expected in [(599.99, True), (600, True), (600.01, False),
                                   (None, True), (0, False)]:
                with self.subTest(platform=platform, warm=warm):
                    listing = Listing(platform, "1", "https://example.com", rooms=1,
                                      price="400 €", warm_rent_eur=warm)
                    self.assertEqual(passes_filters(self.cfg, listing), expected)

    def test_displayed_price_is_the_fallback_when_warm_rent_is_unknown(self):
        listing = Listing("test", "1", "https://example.com", rooms=1, price="450 €")
        self.assertTrue(passes_filters(self.cfg, listing))
        for price in ("650 €", "VB", ""):
            with self.subTest(price=price):
                listing.price = price
                self.assertFalse(passes_filters(self.cfg, listing))
                self.assertTrue(passes_filters(self.cfg, listing, check_rent=False))
        with patch.dict(os.environ, {"SEARCH_MAX_WARM_RENT_EUR": "0"}):
            self.assertTrue(passes_filters(self.cfg, listing))
        # A verified Warmmiete above the cap wins over a cheaper displayed price.
        listing.price, listing.warm_rent_eur = "450 €", 700
        self.assertFalse(passes_filters(self.cfg, listing))

    def test_environment_override_and_validation(self):
        with patch.dict(os.environ, {"SEARCH_MAX_WARM_RENT_EUR": "550,50"}):
            self.assertEqual(resolve_filters(self.cfg)["max_warm_rent_eur"], 550.5)
            listing = Listing("test", "1", "https://example.com", rooms=1, warm_rent_eur=551)
            self.assertFalse(passes_filters(self.cfg, listing))
        for value in ("-1", "nan", "inf", "bad"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_rent_limit_spec(value)

    def test_kleinanzeigen_uses_the_primary_ad_warm_rent(self):
        source = """
          <article id="viewad-product"><div id="viewad-details">
            <li class="addetailslist--detail">Warmmiete
              <span class="addetailslist--detail--value">600,00 €</span></li>
            <li class="addetailslist--detail">Kaution
              <span class="addetailslist--detail--value">1.200 €</span></li>
          </div></article>
          <aside><li class="addetailslist--detail">Warmmiete
            <span class="addetailslist--detail--value">300 €</span></li></aside>
        """
        self.assertEqual(warm_rent_from_html(source, "kleinanzeigen"), 600)
        self.assertIsNone(warm_rent_from_html(source.replace("Warmmiete", "Kaltmiete"), "kleinanzeigen"))

    def test_gesamtmiete_requires_confirmed_heating(self):
        source = """
          <div id="main_column"><div>
            <span class="key_fact_detail">Gesamtmiete</span><b class="key_fact_value">570€</b>
          </div><div id="ad_description_text">TEXT</div></div>
        """
        self.assertIsNone(warm_rent_from_html(source, "wg_gesucht"))
        included = source.replace(
            "TEXT", "In den Nebenkosten sind die Heizkosten enthalten. Strom muss separat angemeldet werden.",
        )
        self.assertEqual(warm_rent_from_html(included, "wg_gesucht"), 570)
        excluded = source.replace("TEXT", "Gesamtmiete ohne Heizung. Heizkosten werden separat bezahlt.")
        self.assertIsNone(warm_rent_from_html(excluded, "wg_gesucht"))

    def test_explicit_warm_rent_in_description(self):
        for text in ("Die Warmmiete beträgt 580 Euro.", "Die Wohnung kostet 580 € warm."):
            source = f'<div id="main_column"><div id="ad_description_text">{text}</div></div>'
            self.assertEqual(warm_rent_from_html(source, "wg_gesucht"), 580)

    def test_complete_rent_components_can_be_added(self):
        source = """<main><dl>
          <dt>Kaltmiete</dt><dd>400 €</dd>
          <dt>Nebenkosten</dt><dd>100 €</dd>
          <dt>Heizkosten</dt><dd>50 €</dd>
        </dl></main>"""
        self.assertEqual(warm_rent_from_html(source, "immowelt"), 550)
        incomplete = source.replace("<dt>Heizkosten</dt><dd>50 €</dd>", "")
        self.assertIsNone(warm_rent_from_html(incomplete, "immowelt"))


if __name__ == "__main__":
    unittest.main()
