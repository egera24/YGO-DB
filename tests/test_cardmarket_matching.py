"""Cardmarket set-code and rarity matching."""

from __future__ import annotations

import unittest

from ygo_app.cardmarket.matching import (
    build_cardmarket_index,
    cardmarket_match_key,
    normalized_set_number,
    printing_match_key,
)


class TestSetCodeNormalization(unittest.TestCase):
    def test_modern_set_code(self):
        self.assertEqual(normalized_set_number("ANPR-ENSE1"), "ANPR-ENSE1")

    def test_legacy_set_code(self):
        self.assertEqual(normalized_set_number("LOB-001"), "LOB-EN001")

    def test_printing_match_key(self):
        key = printing_match_key("RA03-EN172", "Super Rare", "SR")
        self.assertEqual(key, ("RA03-EN172", "super rare"))


class TestCardmarketIndex(unittest.TestCase):
    def test_index_by_set_and_rarity(self):
        products = [
            {
                "expansion_code": "ANPR",
                "card_number": "SE1",
                "card_rarity": "Super Rare",
                "card_id": 123,
                "card_url": "https://example.com/card",
            }
        ]
        index = build_cardmarket_index(products)
        key = cardmarket_match_key("ANPR", "SE1", "Super Rare")
        self.assertIn(key, index)
        self.assertEqual(index[key]["card_id"], 123)


if __name__ == "__main__":
    unittest.main()
