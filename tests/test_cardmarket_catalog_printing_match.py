"""Printing match helpers for Cardmarket catalog."""

from __future__ import annotations

import unittest

from ygo_app.cardmarket.catalog.printing_match import (
    _dedupe_cm_matches_by_expansion_preference,
)


class TestCardmarketCatalogPrintingMatch(unittest.TestCase):
    def test_dedupes_duplicate_card_across_expansions_to_dominant(self):
        cm_matches = [
            {"idProduct": 1, "name": "Bujintei Susanowo", "idExpansion": 1497},
            {"idProduct": 2, "name": "Bujintei Susanowo", "idExpansion": 1498},
        ]
        deduped = _dedupe_cm_matches_by_expansion_preference(
            cm_matches,
            expansion_match_counts={1497: 1, 1498: 5},
        )
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["idExpansion"], 1498)

    def test_keeps_all_when_no_match_counts(self):
        cm_matches = [
            {"idProduct": 1, "name": "Card", "idExpansion": 1497},
            {"idProduct": 2, "name": "Card", "idExpansion": 1498},
        ]
        deduped = _dedupe_cm_matches_by_expansion_preference(
            cm_matches,
            expansion_match_counts=None,
        )
        self.assertEqual(deduped, cm_matches)

    def test_keeps_all_when_dominant_expansion_ties(self):
        cm_matches = [
            {"idProduct": 1, "name": "Card", "idExpansion": 1497},
            {"idProduct": 2, "name": "Card", "idExpansion": 1498},
        ]
        deduped = _dedupe_cm_matches_by_expansion_preference(
            cm_matches,
            expansion_match_counts={1497: 3, 1498: 3},
        )
        self.assertEqual(deduped, cm_matches)


if __name__ == "__main__":
    unittest.main()
