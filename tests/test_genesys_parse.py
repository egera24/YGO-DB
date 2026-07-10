"""Tests for Genesys point list HTML parsing."""

import unittest
from pathlib import Path

from ygo_app.genesys.parse import parse_point_list_file, parse_point_list_html

FIXTURE = Path("DO NOT DELETE/genesys_point_list_html_code.html")

LIVE_STYLE_TABLE_HTML = """
<html><body>
<table class="wikitable sortable">
<tbody>
<tr><th scope="col">Card</th><th scope="col">Cost</th></tr>
<tr><td>"<a href="/wiki/Abyss_Dweller" title="Abyss Dweller">Abyss Dweller</a>"</td><td>100</td></tr>
<tr><td>"<a href="/wiki/Effect_Veiler" title="Effect Veiler">Effect Veiler</a>"</td><td>15</td></tr>
</tbody>
</table>
</body></html>
"""


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

    def test_parse_live_style_table_without_thead(self):
        parsed = parse_point_list_html(
            LIVE_STYLE_TABLE_HTML,
            source_url="https://yugipedia.com/wiki/September_22,_2025_Point_List",
        )
        self.assertEqual(
            parsed["entries"],
            [
                {"card_name_raw": "Abyss Dweller", "points": 100},
                {"card_name_raw": "Effect Veiler", "points": 15},
            ],
        )


if __name__ == "__main__":
    unittest.main()
