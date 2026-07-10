"""Tests for containment-based Yugipedia ↔ Cardmarket matching."""

from __future__ import annotations

import unittest

from ygo_app.cardmarket.containment_matching import (
    cardmarket_matches_printing,
    match_printings_to_cardmarket,
    number_contains,
    parse_yugipedia_set_code,
)


class TestContainmentMatching(unittest.TestCase):
    def test_parse_yugipedia_codes(self):
        self.assertEqual(parse_yugipedia_set_code("LOB-EN062"), ("LOB", "062"))
        self.assertEqual(parse_yugipedia_set_code("LOB-E050"), ("LOB", "050"))
        self.assertEqual(parse_yugipedia_set_code("YS15-END18"), ("YS15", "D18"))

    def test_lob_e050_matches(self):
        self.assertTrue(
            cardmarket_matches_printing(
                cm_expansion_code="LOB",
                cm_card_number="050",
                cm_rarity="Super Rare",
                yugipedia_set_code="LOB-E050",
                yugipedia_rarity_name="Super Rare",
            )
        )

    def test_lob25th_en062_matches(self):
        self.assertTrue(
            cardmarket_matches_printing(
                cm_expansion_code="LOB-25TH",
                cm_card_number="062",
                cm_rarity="Super Rare",
                yugipedia_set_code="LOB-EN062",
                yugipedia_rarity_name="Super Rare",
            )
        )

    def test_number_contains_leading_zeros(self):
        self.assertTrue(number_contains("050", "050"))
        self.assertTrue(number_contains("062", "062"))

    def test_ambiguous_yugipedia_match(self):
        details = [
            {
                "card_data": {
                    "card_id": 1,
                    "card_number": "050",
                    "card_rarity": "Super Rare",
                },
                "expansion_data": {"expansion_code": "LOB"},
            },
            {
                "card_data": {
                    "card_id": 2,
                    "card_number": "050",
                    "card_rarity": "Super Rare",
                },
                "expansion_data": {"expansion_code": "LOB"},
            },
        ]
        catalog = [("LOB-E050", "SR", "Super Rare")]
        _matches, conflicts = match_printings_to_cardmarket(catalog, details)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["type"], "ambiguous_yugipedia_match")


if __name__ == "__main__":
    unittest.main()
