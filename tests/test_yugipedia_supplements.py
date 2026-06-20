"""Tests for Yugipedia supplements scrape helpers."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "yugipedia"

from ygo_app.jobs.scrape_yugipedia_supplements import (
    _cards_with_supplements_done,
    _process_supplements,
    scrape_supplements,
)
from ygo_app.yugipedia.related_links import is_missing_supplement_page_error


class TestMissingSupplementPage(unittest.TestCase):
    def test_404_is_missing(self):
        self.assertTrue(is_missing_supplement_page_error("HTTPError: 404 Client Error"))

    def test_read_timeout_is_missing(self):
        self.assertTrue(
            is_missing_supplement_page_error(
                "ReadTimeout: HTTPSConnectionPool(host='yugipedia.com'): Read timed out."
            )
        )

    def test_connect_timeout_is_missing(self):
        self.assertTrue(is_missing_supplement_page_error("ConnectTimeout: timed out"))

    def test_cloudflare_is_not_missing(self):
        self.assertFalse(is_missing_supplement_page_error("CloudflareError: challenge"))


class TestSupplementsDone(unittest.TestCase):
    def test_force_tips_keeps_card_pending(self):
        cards = [{"id": "483", "name": "Parallel Teleport", "errata": [], "tips": [{"format": "List"}]}]
        done = _cards_with_supplements_done(cards, scrape_errata=True, scrape_tips=True, force_tips=True)
        self.assertEqual(done, set())

    def test_without_force_tips_card_is_done(self):
        cards = [{"id": "483", "name": "Parallel Teleport", "errata": [], "tips": []}]
        done = _cards_with_supplements_done(cards, scrape_errata=True, scrape_tips=True, force_tips=False)
        self.assertEqual(done, {"00000483"})


class TestMaxCardsPreservesCatalog(unittest.TestCase):
    @patch("ygo_app.jobs.scrape_yugipedia_supplements._process_supplements")
    def test_max_cards_only_limits_scrape_not_save(self, mock_process):
        def fake_process(_scraper, card, **kwargs):
            return {"success": True, "card": card, "update": {"tips": []}}

        mock_process.side_effect = fake_process
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cards.json"
            path.write_text(
                json.dumps(
                    [
                        {"id": "1", "name": "Card A"},
                        {"id": "2", "name": "Card B"},
                        {"id": "3", "name": "Card C"},
                    ]
                ),
                encoding="utf-8",
            )
            scrape_supplements(
                cards_path=path,
                set_chronology_path=Path(tmp) / "missing.json",
                max_cards=1,
                scrape_errata=False,
                scrape_tips=True,
                resume=False,
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved), 3)
            self.assertEqual(saved[0]["name"], "Card A")
            self.assertIn("tips", saved[0])
            self.assertNotIn("tips", saved[1])


class TestProcessSupplementsSkip(unittest.TestCase):
    @patch("ygo_app.jobs.scrape_yugipedia_supplements._fetch_supplement_html")
    def test_skips_unavailable_tips_after_timeout(self, mock_fetch):
        mock_fetch.side_effect = [
            (None, "HTTPError: 404 Client Error: Not Found"),
            (None, "ReadTimeout: Read timed out. (read timeout=25)"),
        ]
        card = {"id": "12345678", "name": "Downbeat"}
        result = _process_supplements(
            MagicMock(),
            card,
            set_release_lookup={},
            scrape_errata=True,
            scrape_tips=True,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["update"]["errata"], [])
        self.assertFalse(result["update"]["has_errata"])
        self.assertEqual(result["update"]["tips"], [])

    @patch("ygo_app.jobs.scrape_yugipedia_supplements._fetch_supplement_html")
    def test_no_http_when_detail_scrape_recorded_no_errata_page(self, mock_fetch):
        card = {
            "id": "483",
            "name": "Parallel Teleport",
            "errata_url": None,
            "tips_url": "https://yugipedia.com/wiki/Card_Tips:Parallel_Teleport",
        }
        mock_fetch.return_value = (
            '<div id="mw-content-text"><ul><li>tip</li></ul></div>',
            None,
        )
        result = _process_supplements(
            MagicMock(),
            card,
            set_release_lookup={},
            scrape_errata=True,
            scrape_tips=True,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["update"]["errata"], [])
        self.assertFalse(result["update"]["has_errata"])
        mock_fetch.assert_called_once()
        self.assertIn("Card_Tips", mock_fetch.call_args[0][1])

    @patch("ygo_app.jobs.scrape_yugipedia_supplements._fetch_supplement_html")
    def test_empty_tips_page_stores_empty_list(self, mock_fetch):
        empty_html = (
            FIXTURES / "tips_empty.html"
        ).read_text(encoding="utf-8")
        mock_fetch.return_value = (empty_html, None)
        card = {
            "id": "99999999",
            "name": "No Tips Card",
            "errata_url": None,
            "tips_url": "https://yugipedia.com/wiki/Card_Tips:No_Tips_Card",
        }
        result = _process_supplements(
            MagicMock(),
            card,
            set_release_lookup={},
            scrape_errata=False,
            scrape_tips=True,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["update"]["tips"], [])


if __name__ == "__main__":
    unittest.main()
