"""Tests for Yugipedia card detail scrape behavior."""

import unittest
from unittest.mock import MagicMock, patch

from ygo_app.yugipedia.details import _handle_scrape_result, _process_card


class TestProcessCardNoPrintings(unittest.TestCase):
    @patch("ygo_app.yugipedia.details.parse_card_page")
    @patch("ygo_app.yugipedia.details.fetch_page")
    def test_rejects_when_no_card_sets(self, mock_fetch, mock_parse):
        mock_fetch.return_value = ("<html></html>", None)
        mock_parse.return_value = (
            {"id": "11111111", "name": "OCG Only", "type": "Monster"},
            None,
        )
        input_card = {
            "password": "11111111",
            "name": "OCG Only",
            "url": "https://yugipedia.com/wiki/OCG_Only",
        }
        result = _process_card(MagicMock(), input_card)
        self.assertFalse(result["success"])
        self.assertIn("cts--EN", result["error"])

    @patch("ygo_app.yugipedia.details.parse_card_page")
    @patch("ygo_app.yugipedia.details.fetch_page")
    def test_succeeds_when_card_sets_present(self, mock_fetch, mock_parse):
        mock_fetch.return_value = ("<html></html>", None)
        mock_parse.return_value = (
            {
                "id": "85087012",
                "name": "Card Trooper",
                "card_sets": [{"set_code": "RA03-EN172"}],
            },
            None,
        )
        input_card = {"password": "85087012", "name": "Card Trooper", "url": "http://x"}
        result = _process_card(MagicMock(), input_card)
        self.assertTrue(result["success"])
        self.assertEqual(result["card_data"]["id"], "85087012")


class TestHandleScrapeResultNoPrintings(unittest.TestCase):
    def test_no_printings_error_is_not_retryable(self):
        input_card = {"password": "11111111", "name": "OCG Only"}
        successful: list[dict] = []
        rejected: list[dict] = []
        retryable: list[tuple[dict, str]] = []
        result = {
            "success": False,
            "input_card": input_card,
            "error": "No English (TCG) printings (empty cts--EN)",
        }
        ok = _handle_scrape_result(
            result,
            successful_cards=successful,
            rejected_cards=rejected,
            retryable_failures=retryable,
        )
        self.assertFalse(ok)
        self.assertEqual(len(successful), 0)
        self.assertEqual(len(retryable), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("cts--EN", rejected[0]["rejection_reason"])


if __name__ == "__main__":
    unittest.main()
