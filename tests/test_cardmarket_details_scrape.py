"""Tests for Cardmarket detail price parsing and validation."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ygo_app.cardmarket.card_details_scrape import (
    find_duplicate_card_ids,
    run_card_details_scrape,
    validate_input_card,
)
from ygo_app.cardmarket.http_client import (
    ScrapeShutdown,
    _interruptible_sleep,
    clear_scrape_shutdown,
    request_scrape_shutdown,
)
from ygo_app.cardmarket.parsing import extract_full_price_data
from ygo_app.cardmarket.scrape_session import ScrapeSession


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


class TestDetailsScrapeShutdown(unittest.TestCase):
    def tearDown(self) -> None:
        clear_scrape_shutdown()

    def test_interruptible_sleep_exits_on_shutdown(self):
        clear_scrape_shutdown()
        start = time.monotonic()

        def sleeper() -> None:
            _interruptible_sleep(30.0)

        thread = threading.Thread(target=sleeper)
        thread.start()
        time.sleep(0.05)
        request_scrape_shutdown()
        thread.join(timeout=2.0)

        self.assertFalse(thread.is_alive())
        self.assertLess(time.monotonic() - start, 2.0)

    @patch("ygo_app.cardmarket.card_details_scrape.load_scrape_state", return_value=None)
    @patch("ygo_app.cardmarket.card_details_scrape.create_session_pool", return_value=None)
    @patch("ygo_app.cardmarket.card_details_scrape.fetch_url")
    def test_run_details_scrape_shutdown_saves_checkpoint(
        self, mock_fetch, _mock_pool, _mock_state
    ):
        clear_scrape_shutdown()
        cards = [
            VALID_CARD,
            {
                **VALID_CARD,
                "card_id": 260904,
                "card_name": "Other Card",
                "card_url": "https://www.cardmarket.com/en/YuGiOh/Products/Singles/x/z",
            },
        ]
        call_count = 0

        def fetch_side_effect(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                request_scrape_shutdown()
                raise ScrapeShutdown("Scrape interrupted")
            return DETAIL_HTML, None

        mock_fetch.side_effect = fetch_side_effect
        session = ScrapeSession(
            backend="cloudscraper",
            workers=1,
            discovery_rps=1.0,
            price_rps=1.0,
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            list_path = tmp_path / "cards.json"
            output_path = tmp_path / "details.json"
            rejection_path = tmp_path / "rejections.json"
            list_path.write_text(json.dumps(cards), encoding="utf-8")

            result = run_card_details_scrape(
                input_path=list_path,
                output_path=output_path,
                rejection_path=rejection_path,
                session=session,
            )

            self.assertEqual(result.get("interrupted"), 1)
            self.assertEqual(result["success"], 1)
            saved = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["card_data"]["card_id"], 260903)
