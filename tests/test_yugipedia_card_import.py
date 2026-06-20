"""Tests for Yugipedia scrape → import row mapping."""

from __future__ import annotations

import json
import unittest

from ygo_app.yugipedia.card_import import (
    enrich_ygopro_entry,
    yugipedia_entry_to_import,
    yugipedia_entries_to_import,
)


class TestYugipediaCardImport(unittest.TestCase):
    def test_monster_typeline_and_rank(self):
        entry = {
            "id": "3738521",
            "name": "Bahamut Shark",
            "typeline": ["Sea Serpent", "Xyz", "Effect"],
            "attribute": "WATER",
            "type": "Sea Serpent",
            "mechanic": "Xyz",
            "rank": 4,
            "atk": 2600,
            "def": 2100,
            "summoning_condition": "2 Level 4 WATER monsters",
            "archetype": "Shark",
            "card_sets": [{"set_code": "RA03-EN001", "set_name": "QCB", "set_rarity": "SR"}],
        }
        row = yugipedia_entry_to_import(entry)
        assert row is not None
        self.assertEqual(row["category"], "Monster")
        types = json.loads(row["types"])
        self.assertIn("Sea Serpent", types)
        self.assertIn("Xyz", types)
        self.assertEqual(row["rank"], 4)
        self.assertIsNone(row["level"])
        self.assertEqual(row["mechanic"], "Xyz")
        self.assertEqual(row["summoning_condition"], "2 Level 4 WATER monsters")

    def test_spell_property_as_types(self):
        entry = {
            "id": "80181649",
            "name": "Parallel eXceed",
            "type": "Spell",
            "property": "Quick-Play",
            "archetype": "Teleport",
            "card_sets": [{"set_code": "DUAD-EN001", "set_name": "D", "set_rarity": "SR"}],
        }
        row = yugipedia_entry_to_import(entry)
        assert row is not None
        self.assertEqual(row["category"], "Spell")
        self.assertEqual(json.loads(row["types"]), ["Quick-Play"])
        self.assertIsNone(row["mechanic"])

    def test_link_markers_json(self):
        entry = {
            "id": "12345678",
            "name": "Test Link",
            "typeline": ["Cyberse", "Link", "Effect"],
            "type": "Cyberse",
            "attribute": "DARK",
            "link_rating": 3,
            "link_markers": ["Top", "Left", "Right"],
            "atk": 2300,
            "card_sets": [{"set_code": "X-EN001", "set_name": "S", "set_rarity": "SR"}],
        }
        row = yugipedia_entry_to_import(entry)
        assert row is not None
        self.assertEqual(json.loads(row["link_markers"]), ["Top", "Left", "Right"])
        self.assertEqual(row["link_rating"], 3)

    def test_errata_and_tips_fields(self):
        entry = {
            "id": "84893333",
            "name": "Abyss Dweller",
            "typeline": ["Sea Serpent", "Xyz", "Effect"],
            "type": "Sea Serpent",
            "attribute": "WATER",
            "rank": 4,
            "atk": 1700,
            "def": 1400,
            "card_sets": [{"set_code": "ABYR-EN084", "set_name": "Abyss Rising", "set_rarity": "SR"}],
            "has_errata": True,
            "last_erratum_date": "2019-10-11",
            "errata": [
                {
                    "language": "English",
                    "version_index": 0,
                    "version_label": "Original",
                    "lore_text": "Original",
                }
            ],
            "tips": [{"format": "Traditional Format", "tips": ["Tip one"]}],
        }
        row = yugipedia_entry_to_import(entry)
        assert row is not None
        self.assertTrue(row["has_errata"])
        self.assertEqual(row["last_erratum_date"], "2019-10-11")
        self.assertEqual(len(row["errata"]), 1)
        self.assertIn("Traditional Format", row["tips"])
        entries = [
            {"id": "11111111", "name": "X", "typeline": ["Dragon"], "type": "Dragon"},
            {
                "id": "85087012",
                "name": "Card Trooper",
                "typeline": ["Machine", "Effect"],
                "type": "Machine",
                "card_sets": [{"set_code": "RA03-EN172", "set_name": "Q", "set_rarity": "SR"}],
            },
        ]
        out = yugipedia_entries_to_import(entries)
        self.assertEqual(len(out), 1)

    def test_enrich_ygopro_xyz_rank(self):
        entry = enrich_ygopro_entry(
            {
                "id": 3738521,
                "name": "Bahamut Shark",
                "type": "XYZ Monster",
                "frameType": "xyz",
                "race": "Sea Serpent",
                "level": 4,
                "atk": 2600,
                "def": 2100,
            }
        )
        self.assertEqual(entry["category"], "Monster")
        self.assertEqual(entry["rank"], 4)
        self.assertIsNone(entry["level"])


if __name__ == "__main__":
    unittest.main()
