"""Tests for Cardmarket detail price parsing and validation."""

from __future__ import annotations

import unittest

from ygo_app.cardmarket.card_details_scrape import (
    find_duplicate_card_ids,
    validate_input_card,
)
from ygo_app.cardmarket.parsing import extract_full_price_data


DETAIL_HTML = """
<dt class="col-6">From</dt><dd class="col-6">0,03 €</dd>
<dt class="col-6">Price Trend</dt><dd class="col-6"><span>1,35 €</span></dd>
<dt class="col-6">30-days average price</dt><dd class="col-6"><span>1,26 €</span></dd>
<dt class="col-6">7-days average price</dt><dd class="col-6"><span>1,33 €</span></dd>
<dt class="col-6">1-day average price</dt><dd class="col-6"><span>0,80 €</span></dd>
"""

NA_HTML = """
<dt>From</dt><dd>N/A</dd>
<dt>Price Trend</dt><dd>1,00 €</dd>
<dt>30-days average price</dt><dd>1,00 €</dd>
<dt>7-days average price</dt><dd>1,00 €</dd>
<dt>1-day average price</dt><dd>1,00 €</dd>
"""


VALID_CARD = {
    "expansion_id": 1433,
    "expansion_name": "ZTIN",
    "expansion_code": "ZTIN",
    "card_id": 260903,
    "card_name": "Number 20: Giga-Brilliant",
    "card_number": "V02",
    "card_rarity": "Ultimate Rare",
    "card_url": "https://www.cardmarket.com/en/YuGiOh/Products/Singles/x/y",
}


class TestCardDetailsScrape(unittest.TestCase):
    def test_extract_full_price_data_success(self):
        prices, has_na = extract_full_price_data(DETAIL_HTML)
        assert prices is not None
        self.assertFalse(has_na)
        self.assertEqual(prices["low_price"], 0.03)
        self.assertEqual(prices["trend_price"], 1.35)
        self.assertEqual(prices["avg_30_price"], 1.26)

    def test_extract_full_price_data_rejects_na(self):
        prices, has_na = extract_full_price_data(NA_HTML)
        self.assertIsNone(prices)
        self.assertTrue(has_na)

    def test_validate_input_card(self):
        ok, err = validate_input_card(VALID_CARD)
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_validate_rejects_missing_url(self):
        bad = dict(VALID_CARD)
        bad["card_url"] = "http://insecure"
        ok, _ = validate_input_card(bad)
        self.assertFalse(ok)

    def test_find_duplicate_card_ids(self):
        cards = [dict(VALID_CARD), dict(VALID_CARD)]
        self.assertEqual(find_duplicate_card_ids(cards), [260903])
