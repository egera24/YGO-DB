"""Tests for Cardmarket collector_number parsing."""

from __future__ import annotations

import unittest
from pathlib import Path

from ygo_app.cardmarket.product_list import extract_cards_from_html

SAMPLES = Path(__file__).resolve().parents[1] / "cardmarket" / "debug_samples"


class TestCollectorNumberParsing(unittest.TestCase):
    def test_ys15_dust_tornado(self):
        html = (SAMPLES / "ys15-dust-tornado.html").read_text(encoding="utf-8")
        cards, code = extract_cards_from_html(
            html, expansion_id=1651, expansion_name="YS15 Deck", expansion_code="YS15"
        )
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["card_number"], "D18")
        self.assertEqual(cards[0]["card_name"], "Dust Tornado")
        self.assertEqual(code, "YS15")

    def test_lob_mystical_elf(self):
        html = (SAMPLES / "lob-mystical-elf.html").read_text(encoding="utf-8")
        cards, code = extract_cards_from_html(
            html, expansion_id=1064, expansion_name="LOB", expansion_code="LOB"
        )
        self.assertEqual(cards[0]["card_number"], "050")
        self.assertEqual(code, "LOB")

    def test_lob25th_mystical_elf(self):
        html = (SAMPLES / "lob25th-mystical-elf.html").read_text(encoding="utf-8")
        cards, code = extract_cards_from_html(
            html,
            expansion_id=5339,
            expansion_name="LOB 25th",
            expansion_code="LOB-25TH",
        )
        self.assertEqual(cards[0]["card_number"], "062")
        self.assertEqual(code, "LOB-25TH")

    def test_ignores_hidden_row_index(self):
        html = (SAMPLES / "ys15-dust-tornado.html").read_text(encoding="utf-8")
        cards, _ = extract_cards_from_html(html, expansion_id=1651, expansion_name="YS15")
        self.assertNotEqual(cards[0]["card_number"], "2")


if __name__ == "__main__":
    unittest.main()
