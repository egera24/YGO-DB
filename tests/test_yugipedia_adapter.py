"""Tests for Yugipedia → API catalog adapter."""

import unittest

from ygo_app.yugipedia.adapter import yugipedia_card_to_api, yugipedia_entries_to_api


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
            "image_url": "https://ms.yugipedia.com//6/65/CardTrooper-25YC-EN-SR-LE.png",
            "image_url_small": (
                "https://ms.yugipedia.com//thumb/6/65/CardTrooper-25YC-EN-SR-LE.png/"
                "150px-CardTrooper-25YC-EN-SR-LE.png"
            ),
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
        self.assertIn("ms.yugipedia.com", api["card_images"][0]["image_url"])
        self.assertIn("CardTrooper-25YC-EN-SR-LE.png", api["card_images"][0]["image_url"])

    def test_monster_without_image_url(self):
        entry = {
            "id": "85087012",
            "name": "Card Trooper",
            "typeline": ["Machine", "Effect"],
            "type": "Machine",
        }
        api = yugipedia_card_to_api(entry)
        assert api is not None
        self.assertIsNone(api["card_images"][0]["image_url"])
        self.assertIsNone(api["card_images"][0]["image_url_small"])
        self.assertEqual(api["ygoprodeck_url"], "https://ygoprodeck.com/card/85087012")

    def test_entries_without_card_sets_skipped(self):
        entries = [
            {
                "id": "11111111",
                "name": "OCG Only",
                "typeline": ["Dragon", "Normal"],
                "type": "Dragon",
            },
            {
                "id": "85087012",
                "name": "Card Trooper",
                "typeline": ["Machine", "Effect"],
                "type": "Machine",
                "card_sets": [{"set_code": "RA03-EN172", "set_name": "QCB", "set_rarity": "SR"}],
            },
        ]
        api = yugipedia_entries_to_api(entries)
        self.assertEqual(len(api), 1)
        self.assertEqual(api[0]["id"], 85087012)

    def test_spell_card(self):
        entry = {
            "id": "80181649",
            "name": "Test Spell",
            "type": "Spell",
            "property": "Continuous",
            "description": "Do something.",
            "image_url": "https://ms.yugipedia.com//a/a6/ParallelTeleport-DUAD-EN-SR-1E.png",
        }
        api = yugipedia_card_to_api(entry)
        self.assertEqual(api["frameType"], "spell")
        self.assertIn("Continuous", api["humanReadableCardType"])
        self.assertIn("ms.yugipedia.com", api["card_images"][0]["image_url"])

    def test_xyz_rank_not_in_level(self):
        entry = {
            "id": "3738521",
            "name": "Bahamut Shark",
            "typeline": ["Sea Serpent", "Xyz", "Effect"],
            "type": "Sea Serpent",
            "rank": 4,
            "atk": 2600,
            "def": 2100,
        }
        api = yugipedia_card_to_api(entry)
        assert api is not None
        self.assertIsNone(api["level"])


if __name__ == "__main__":
    unittest.main()
