"""Tests for Genesys point list HTML parsing."""

import unittest
from pathlib import Path

from ygo_app.genesys.parse import parse_point_list_file

FIXTURE = Path("DO NOT DELETE/genesys_point_list_html_code.html")


class GenesysParseTests(unittest.TestCase):
    @unittest.skipUnless(FIXTURE.exists(), "fixture HTML missing")
    def test_parse_fixture_contains_entries(self):
        parsed = parse_point_list_file(
            FIXTURE,
            source_url="https://yugipedia.com/wiki/September_22,_2025_Point_List",
        )
        self.assertGreater(len(parsed["entries"]), 10)
        dweller = next(
            (e for e in parsed["entries"] if e["card_name_raw"] == "Abyss Dweller"),
            None,
        )
        self.assertIsNotNone(dweller)
        self.assertEqual(dweller["points"], 100)
        self.assertIn("September_24,_2025_Point_List", " ".join(parsed["related_urls"]))


if __name__ == "__main__":
    unittest.main()
