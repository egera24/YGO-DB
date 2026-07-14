"""Collection row identity helpers."""

from __future__ import annotations

import unittest

from ygo_app.collection_identity import (
    COLLECTION_NOTES_MAX_LENGTH,
    collection_item_key,
    normalize_collection_condition,
    normalize_collection_edition,
    normalize_collection_notes,
)


class TestCollectionIdentity(unittest.TestCase):
    def test_normalize_edition_aliases(self):
        cases = {
            None: "Unlimited",
            "": "Unlimited",
            "Limited": "Limited Edition",
            "limited ed.": "Limited Edition",
            "LE": "Limited Edition",
            "1st Edition": "1st Edition",
            "First Edition": "1st Edition",
            "first ed": "1st Edition",
            "1st": "1st Edition",
            "1stEdition": "1st Edition",
            "Unlimited": "Unlimited",
            "UE": "Unlimited",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_collection_edition(raw), expected)

    def test_normalize_condition_aliases(self):
        cases = {
            None: None,
            "": None,
            "   ": None,
            "NearMint": "NearMint",
            "Near Mint": "NearMint",
            "NM": "NearMint",
            "Light Played": "LightPlayed",
            "LP": "LightPlayed",
            "light-played": "LightPlayed",
            "Poor": "Poor",
            "PO": "Poor",
            "Custom Grade": "Custom Grade",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_collection_condition(raw), expected)

    def test_normalize_collection_notes(self):
        self.assertIsNone(normalize_collection_notes(None))
        self.assertIsNone(normalize_collection_notes(""))
        self.assertIsNone(normalize_collection_notes("   "))
        self.assertEqual(normalize_collection_notes("  binder A  "), "binder A")
        ok = "x" * COLLECTION_NOTES_MAX_LENGTH
        self.assertEqual(normalize_collection_notes(ok), ok)
        with self.assertRaises(ValueError):
            normalize_collection_notes("x" * (COLLECTION_NOTES_MAX_LENGTH + 1))

    def test_collection_item_key_treats_aliases_as_equal(self):
        key_a = collection_item_key(
            "LOB-001",
            "(UR)",
            edition="First Edition",
            condition="Light Played",
        )
        key_b = collection_item_key(
            "LOB-001",
            "(UR)",
            edition="1st Edition",
            condition="LightPlayed",
        )
        self.assertEqual(key_a, key_b)


if __name__ == "__main__":
    unittest.main()
