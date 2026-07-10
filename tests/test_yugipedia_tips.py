"""Tests for Yugipedia tips parsing."""

import unittest
from pathlib import Path

from ygo_app.yugipedia.tips import parse_tips_html

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "yugipedia"


class TestTipsParse(unittest.TestCase):
    def test_abyss_dweller_traditional(self):
        html = (FIXTURES / "tips_abyss_dweller.html").read_text(encoding="utf-8")
        sections = parse_tips_html(html)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["format"], "Traditional Format")
        tips = sections[0]["tips"]
        self.assertGreaterEqual(len(tips), 5)
        self.assertTrue(any("Zombie" in t for t in tips))
        self.assertTrue(any("Side Deck" in t for t in tips))
        self.assertTrue(any("Atlantean Dragoons" in t for t in tips))

    def test_parallel_teleport_pre_h2_and_no_list(self):
        html = (FIXTURES / "tips_parallel_teleport.html").read_text(encoding="utf-8")
        sections = parse_tips_html(html)
        formats = [s["format"] for s in sections]
        self.assertNotIn("List", formats)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["format"], "")
        tips = sections[0]["tips"]
        self.assertEqual(len(tips), 1)
        self.assertIn("Mind Procedure", tips[0])
        self.assertIn("generic searchers", tips[0])
        self.assertNotIn("Level 7 or lower", tips[0])

    def test_empty_page_returns_no_sections(self):
        html = (FIXTURES / "tips_empty.html").read_text(encoding="utf-8")
        sections = parse_tips_html(html)
        self.assertEqual(sections, [])


if __name__ == "__main__":
    unittest.main()
