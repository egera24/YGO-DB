"""Unit tests for Cardmarket catalog name normalization."""

from __future__ import annotations

import unittest

from ygo_app.cardmarket.catalog.normalize import normalize_card_name


class TestNormalizeCardName(unittest.TestCase):
    def test_live_twin_branding_star_matches_cardmarket_form(self):
        yugipedia = "Live\u2606Twin Lil-la Sweet"
        cardmarket = "LiveTwin Lil-la Sweet"
        expected = "livetwin lil-la sweet"
        self.assertEqual(normalize_card_name(yugipedia), expected)
        self.assertEqual(normalize_card_name(cardmarket), expected)

    def test_evil_twin_branding_star_matches_cardmarket_form(self):
        yugipedia = "Evil\u2605Twin Ki-sikil Deal"
        cardmarket = "EvilTwin Ki-sikil Deal"
        expected = "eviltwin ki-sikil deal"
        self.assertEqual(normalize_card_name(yugipedia), expected)
        self.assertEqual(normalize_card_name(cardmarket), expected)

    def test_other_punctuation_becomes_spaces(self):
        self.assertEqual(normalize_card_name("Number 39: Utopia"), "number 39 utopia")

    def test_hyphens_and_apostrophes_preserved(self):
        self.assertEqual(normalize_card_name("Yu-Gi-Oh! 5D's"), "yu-gi-oh 5d's")
        self.assertEqual(normalize_card_name("Lil-la Sweet"), "lil-la sweet")
