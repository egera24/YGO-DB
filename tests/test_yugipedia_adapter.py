"""Tests for Yugipedia → API catalog adapter."""

import unittest

from ygo_app.yugipedia.adapter import yugipedia_card_to_api


class TestYugipediaAdapter(unittest.TestCase):
    def test_monster_with_multi_rarity_sets(self):
        entry = {
            "id": "85087012",
            "name": "Card Trooper",
            "typeline": ["Machine", "Effect"],
            "attribute": "EARTH",
            "type": "Machine",
            "effect": "yes",
            "level": 3,
            "atk": 0,
            "def": 0,
            "description": "Test",
            "card_sets": [
                {
                    "set_code": "RA03-EN172",
                    "set_name": "Quarter Century Bonanza",
                    "set_rarity": "Platinum Secret Rare",
                    "set_rarity_code": "PScR",
                },
                {
                    "set_code": "RA03-EN172",
                    "set_name": "Quarter Century Bonanza",
                    "set_rarity": "Quarter Century Secret Rare",
                    "set_rarity_code": "QCR",
                },
            ],
        }
        api = yugipedia_card_to_api(entry)
        self.assertIsNotNone(api)
        assert api is not None
        self.assertEqual(api["id"], 85087012)
        self.assertEqual(len(api["card_sets"]), 2)
        self.assertTrue(
            api["card_images"][0]["image_url"].endswith("/85087012.jpg")
        )

    def test_spell_card(self):
        entry = {
            "id": "80181649",
            "name": "Test Spell",
            "type": "Spell",
            "property": "Continuous",
            "description": "Do something.",
        }
        api = yugipedia_card_to_api(entry)
        self.assertEqual(api["frameType"], "spell")
        self.assertIn("Continuous", api["humanReadableCardType"])


if __name__ == "__main__":
    unittest.main()
