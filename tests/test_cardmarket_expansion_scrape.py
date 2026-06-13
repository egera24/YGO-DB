"""Tests for Cardmarket expansion list parsing."""

from __future__ import annotations

import unittest

from ygo_app.cardmarket.expansions import is_ocg_expansion, parse_expansions_from_html


SAMPLE_HTML = """
<select name="idExpansion">
  <option value="0">All</option>
  <option value="1651">2-Player Starter Deck Yuya &amp; Declan</option>
  <option value="9999">Some OCG Set OCG</option>
  <option value="1651">Duplicate ID</option>
</select>
"""


class TestExpansionListParse(unittest.TestCase):
    def test_parses_tcg_and_skips_ocg(self):
        rows = parse_expansions_from_html(SAMPLE_HTML)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["expansion_id"], 1651)
        self.assertIn("&", rows[0]["expansion_name"])

    def test_is_ocg_expansion(self):
        self.assertTrue(is_ocg_expansion("Duelist Pack OCG"))
        self.assertFalse(is_ocg_expansion("Legend of Blue Eyes"))
