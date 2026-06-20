"""Tests for Yugipedia errata parsing."""

import unittest
from pathlib import Path

from ygo_app.yugipedia.errata import compute_errata_flags, parse_errata_html

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "yugipedia"
SET_LOOKUP = {
    "ABYR": "2012-07-21",
    "DUDE": "2019-10-11",
    "MFC": "2002-10-01",
    "GLD3": "2010-06-23",
    "SGX3": "2022-05-20",
}


class TestErrataParse(unittest.TestCase):
    def test_abyss_dweller_two_columns(self):
        html = (FIXTURES / "errata_abyss_dweller.html").read_text(encoding="utf-8")
        versions = parse_errata_html(html, set_release_lookup=SET_LOOKUP)
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0]["version_label"], "Original")
        self.assertEqual(versions[1]["version_label"], "First erratum")
        self.assertEqual(versions[0]["set_code"], "ABYR-EN084")
        self.assertEqual(versions[1]["set_code"], "DUDE-EN016")
        self.assertEqual(versions[1]["release_date"], "2019-10-11")
        self.assertIn("2 Level 4 monsters", versions[0]["lore_text"])
        self.assertIn("Quick Effect", versions[1]["lore_text"])

    def test_amazoness_three_columns(self):
        html = (FIXTURES / "errata_amazoness_paladin.html").read_text(encoding="utf-8")
        versions = parse_errata_html(html, set_release_lookup=SET_LOOKUP)
        self.assertEqual(len(versions), 3)
        labels = [v["version_label"] for v in versions]
        self.assertEqual(labels, ["Original", "First erratum", "Second erratum"])

    def test_compute_flags(self):
        html = (FIXTURES / "errata_abyss_dweller.html").read_text(encoding="utf-8")
        versions = parse_errata_html(html, set_release_lookup=SET_LOOKUP)
        has_errata, last_date = compute_errata_flags(versions)
        self.assertTrue(has_errata)
        self.assertEqual(last_date, "2019-10-11")


if __name__ == "__main__":
    unittest.main()
