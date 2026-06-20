"""Tests for Yugipedia Set chronology parsing."""

import unittest
from pathlib import Path

from ygo_app.yugipedia.date_parse import parse_yugipedia_date
from ygo_app.yugipedia.set_chronology import (
    parse_set_chronology_html,
    set_abbr_from_code,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "yugipedia"


class TestDateParse(unittest.TestCase):
    def test_long_month(self):
        self.assertEqual(parse_yugipedia_date("8 March 2002").isoformat(), "2002-03-08")

    def test_iso(self):
        self.assertEqual(parse_yugipedia_date("2024-11-07").isoformat(), "2024-11-07")


class TestSetChronology(unittest.TestCase):
    def test_tcg_snippet(self):
        html = (FIXTURES / "set_chronology_tcg_snippet.html").read_text(encoding="utf-8")
        rows = parse_set_chronology_html(html)
        by_abbr = {row["abbr"]: row for row in rows}
        self.assertIn("LOB", by_abbr)
        self.assertIn("ABYR", by_abbr)
        self.assertEqual(by_abbr["LOB"]["release_date"], "2002-03-08")
        self.assertEqual(by_abbr["ABYR"]["release_date"], "2012-07-21")
        self.assertEqual(
            by_abbr["LOB"]["name"],
            "Legend of Blue Eyes White Dragon",
        )
        self.assertIn("Duel Monsters", by_abbr["LOB"]["series"])


class TestSetAbbrFromCode(unittest.TestCase):
    def test_printing_code(self):
        self.assertEqual(set_abbr_from_code("ABYR-EN084"), "ABYR")
        self.assertEqual(set_abbr_from_code("DUDE-EN016"), "DUDE")


if __name__ == "__main__":
    unittest.main()
