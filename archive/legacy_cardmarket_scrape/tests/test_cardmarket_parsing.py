"""Cardmarket price parsing."""

from __future__ import annotations

import unittest

from ygo_app.cardmarket.parsing import extract_price_data, parse_price


class TestParsePrice(unittest.TestCase):
    def test_comma_decimal(self):
        value, is_na = parse_price("0,50 €")
        self.assertFalse(is_na)
        self.assertAlmostEqual(value, 0.50)

    def test_thousands(self):
        value, is_na = parse_price("9.999,99 €")
        self.assertFalse(is_na)
        self.assertAlmostEqual(value, 9999.99)

    def test_na(self):
        value, is_na = parse_price("N/A")
        self.assertTrue(is_na)
        self.assertIsNone(value)

    def test_zero(self):
        value, is_na = parse_price("0,00 €")
        self.assertFalse(is_na)
        self.assertEqual(value, 0.0)


class TestExtractPriceData(unittest.TestCase):
    def test_partial_prices_allowed(self):
        html = """
        <dl>
          <dt>From</dt><dd>0,03 €</dd>
          <dt>Price Trend</dt><dd><span>1,35 €</span></dd>
          <dt>30-days average price</dt><dd><span>1,26 €</span></dd>
        </dl>
        """
        prices = extract_price_data(html)
        self.assertAlmostEqual(prices["low_price"], 0.03)
        self.assertAlmostEqual(prices["trend_price"], 1.35)
        self.assertAlmostEqual(prices["avg_price"], 1.26)

    def test_missing_fields_stay_none(self):
        html = "<dl><dt>From</dt><dd>1,00 €</dd></dl>"
        prices = extract_price_data(html)
        self.assertAlmostEqual(prices["low_price"], 1.0)
        self.assertIsNone(prices["avg_price"])
        self.assertIsNone(prices["trend_price"])


if __name__ == "__main__":
    unittest.main()
