"""Tests for Cardmarket scrape pacing and checkpoint intervals."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from ygo_app.cardmarket.card_details_scrape import SAVE_INTERVAL
from ygo_app.cardmarket.card_list_scrape import CHECKPOINT_EVERY
from ygo_app.cardmarket.constants import INTER_PAGE_DELAY_BROWSER
from ygo_app.cardmarket.http_client import sleep_inter_page_delay


class TestCardmarketPacing(unittest.TestCase):
    def test_job2_checkpoint_every_five(self):
        self.assertEqual(CHECKPOINT_EVERY, 5)

    def test_job3_save_interval_five(self):
        self.assertEqual(SAVE_INTERVAL, 5)

    def test_browser_inter_request_delay_range(self):
        self.assertEqual(INTER_PAGE_DELAY_BROWSER, (2.0, 8.0))

    @patch("ygo_app.cardmarket.http_client.time.sleep")
    @patch("ygo_app.cardmarket.http_client.random.uniform", return_value=5.5)
    def test_sleep_inter_page_delay_browser(self, mock_uniform, mock_sleep):
        sleep_inter_page_delay("playwright")
        mock_uniform.assert_called_once_with(2.0, 8.0)
        mock_sleep.assert_called_once_with(5.5)
