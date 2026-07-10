"""Tests for Yugipedia errata parsing."""

import unittest
from pathlib import Path

from ygo_app.yugipedia.errata import (
    ERRATA_UI_LANGUAGE,
    compute_errata_flags,
    filter_errata_by_language,
    parse_errata_html,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "yugipedia"
SET_LOOKUP = {
    "ABYR": "2012-07-21",
    "DUDE": "2019-10-11",
    "MFC": "2002-10-01",
    "GLD3": "2010-06-23",
    "SGX3": "2022-05-20",
    "MRD": "2002-06-26",
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
        self.assertIn("\n", versions[0]["lore_text"])
        self.assertNotIn("\nIncreases\n", versions[0]["lore_text"])
        self.assertIn("<ins>", versions[1]["lore_html"])
        self.assertIn("<b>", versions[0]["lore_html"])

    def test_amazoness_three_columns(self):
        html = (FIXTURES / "errata_amazoness_paladin.html").read_text(encoding="utf-8")
        versions = parse_errata_html(html, set_release_lookup=SET_LOOKUP)
        self.assertEqual(len(versions), 3)
        labels = [v["version_label"] for v in versions]
        self.assertEqual(labels, ["Original", "First erratum", "Second erratum"])

    def test_castle_of_dark_illusions_twocolumn_blocks(self):
        html = (FIXTURES / "errata_castle_of_dark_illusions.html").read_text(
            encoding="utf-8"
        )
        versions = parse_errata_html(html, set_release_lookup=SET_LOOKUP)
        self.assertEqual(len(versions), 4)
        labels = [v["version_label"] for v in versions]
        self.assertEqual(
            labels,
            ["Original", "First erratum", "Second erratum", "Third erratum"],
        )
        self.assertEqual(versions[0]["set_code"], "MRD-073")
        self.assertEqual(versions[1]["set_code"], "MRD-EN073")
        self.assertEqual(versions[2]["set_code"], "MRD-073")
        self.assertEqual(versions[3]["set_code"], "MRD-EN073")
        self.assertEqual(versions[1]["release_date"], "2002-06-26")

        original = versions[0]["lore_text"]
        self.assertIn("FLIP: Increases the ATK and DEF", original)
        self.assertNotIn("\nIncreases\n", original)

        self.assertIn("<del>", versions[1]["lore_html"])
        self.assertIn("<ins>", versions[2]["lore_html"])
        self.assertIn("<ins>", versions[3]["lore_html"])
        self.assertIn("<b>", versions[1]["lore_html"])
        self.assertIn("<i>", versions[2]["lore_html"])
        first_erratum = versions[1]["lore_text"]
        self.assertIn("Increase the ATK and DEF of", first_erratum)
        self.assertIn("gain", versions[2]["lore_text"])
        self.assertIn("Increases the ATK and DEF", versions[3]["lore_text"])

    def test_compute_flags(self):
        html = (FIXTURES / "errata_abyss_dweller.html").read_text(encoding="utf-8")
        versions = parse_errata_html(html, set_release_lookup=SET_LOOKUP)
        has_errata, last_date = compute_errata_flags(versions)
        self.assertTrue(has_errata)
        self.assertEqual(last_date, "2019-10-11")

    def test_filter_english_only(self):
        html = (FIXTURES / "errata_abyss_dweller.html").read_text(encoding="utf-8")
        versions = parse_errata_html(html, set_release_lookup=SET_LOOKUP)
        english = filter_errata_by_language(versions)
        self.assertTrue(all(v["language"] == ERRATA_UI_LANGUAGE for v in english))
        self.assertEqual(len(english), 2)

    def test_compute_flags_no_english(self):
        versions = [
            {
                "language": "Japanese",
                "version_index": 0,
                "version_label": "Original",
                "release_date": None,
            },
            {
                "language": "Japanese",
                "version_index": 1,
                "version_label": "First erratum",
                "release_date": "2019-10-11",
            },
        ]
        has_errata, last_date = compute_errata_flags(versions)
        self.assertFalse(has_errata)
        self.assertIsNone(last_date)


if __name__ == "__main__":
    unittest.main()
