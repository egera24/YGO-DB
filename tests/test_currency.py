"""EUR/HUF exchange rate helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from ygo_app import currency


class TestCurrency(unittest.TestCase):
    def setUp(self):
        currency.clear_eur_huf_cache()

    def tearDown(self):
        currency.clear_eur_huf_cache()

    @patch("ygo_app.currency.requests.get")
    def test_get_eur_huf_rate_live(self, get_mock):
        response = get_mock.return_value
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "amount": 1.0,
            "base": "EUR",
            "date": "2026-07-10",
            "rates": {"HUF": 392.15},
        }

        rate = currency.get_eur_huf_rate(force_refresh=True)
        self.assertEqual(rate.rate, 392.15)
        self.assertEqual(rate.source, "live")
        self.assertEqual(rate.as_of, "2026-07-10")

        cached = currency.get_eur_huf_rate()
        self.assertEqual(cached.rate, 392.15)
        self.assertEqual(cached.source, "live")
        get_mock.assert_called_once()

    @patch("ygo_app.currency.requests.get")
    @patch("ygo_app.currency.EUR_HUF_RATE", 401.5)
    def test_get_eur_huf_rate_fallback_on_api_failure(self, get_mock):
        get_mock.side_effect = currency.requests.RequestException("network error")

        rate = currency.get_eur_huf_rate(force_refresh=True)
        self.assertEqual(rate.rate, 401.5)
        self.assertEqual(rate.source, "fallback")
        self.assertIsNone(rate.as_of)

    @patch("ygo_app.currency.requests.get")
    @patch("ygo_app.currency.time.monotonic")
    def test_get_eur_huf_rate_cache_expires(self, monotonic_mock, get_mock):
        monotonic_mock.side_effect = [0.0, 0.0, currency.CACHE_TTL_SECONDS + 1]

        response = get_mock.return_value
        response.raise_for_status.return_value = None
        response.json.side_effect = [
            {
                "amount": 1.0,
                "base": "EUR",
                "date": "2026-07-10",
                "rates": {"HUF": 390.0},
            },
            {
                "amount": 1.0,
                "base": "EUR",
                "date": "2026-07-11",
                "rates": {"HUF": 395.0},
            },
        ]

        first = currency.get_eur_huf_rate(force_refresh=True)
        second = currency.get_eur_huf_rate()
        third = currency.get_eur_huf_rate()

        self.assertEqual(first.rate, 390.0)
        self.assertEqual(second.rate, 390.0)
        self.assertEqual(third.rate, 395.0)
        self.assertEqual(get_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
