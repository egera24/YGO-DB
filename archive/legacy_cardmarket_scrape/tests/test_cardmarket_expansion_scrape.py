"""Tests for Cardmarket expansion list parsing."""

from __future__ import annotations

import unittest

from ygo_app.cardmarket.expansions import (
    REJECTION_REASON_NOT_TCG,
    build_exclusion_rejection,
    exclusion_category,
    is_non_tcg_expansion,
    is_ocg_expansion,
    parse_expansions_from_html,
    parse_expansions_from_html_with_exclusions,
    partition_expansions,
)


SAMPLE_HTML = """
<select name="idExpansion">
  <option value="0">All</option>
  <option value="1651">2-Player Starter Deck Yuya &amp; Declan</option>
  <option value="9999">Some OCG Set OCG</option>
  <option value="5758">Rush Duel: Starter Deck Set - Yuga vs. Luke</option>
  <option value="6001">Battle of Chaos (Japanese)</option>
  <option value="6002">Legendary Duelists (Korean)</option>
  <option value="1651">Duplicate ID</option>
</select>
"""


class TestExpansionListParse(unittest.TestCase):
    def test_parses_tcg_and_skips_non_tcg(self):
        rows = parse_expansions_from_html(SAMPLE_HTML)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["expansion_id"], 1651)
        self.assertIn("&", rows[0]["expansion_name"])

    def test_parse_with_exclusions_returns_rejections(self):
        tcg, excluded = parse_expansions_from_html_with_exclusions(SAMPLE_HTML)
        self.assertEqual(len(tcg), 1)
        self.assertEqual(tcg[0]["expansion_id"], 1651)
        self.assertEqual({r["expansion_id"] for r in excluded}, {9999, 5758, 6001, 6002})
        categories = {r["exclusion_category"] for r in excluded}
        self.assertEqual(categories, {"ocg", "rush_duel", "japanese", "korean"})

    def test_exclusion_category_patterns(self):
        self.assertEqual(exclusion_category("Duelist Pack OCG"), "ocg")
        self.assertEqual(
            exclusion_category("Rush Duel: Starter Deck Set - Yuga vs. Luke"),
            "rush_duel",
        )
        self.assertEqual(exclusion_category("Battle of Chaos (Japanese)"), "japanese")
        self.assertEqual(exclusion_category("Legendary Duelists (Korean)"), "korean")
        self.assertIsNone(exclusion_category("Legend of Blue Eyes"))

    def test_is_ocg_expansion(self):
        self.assertTrue(is_ocg_expansion("Duelist Pack OCG"))
        self.assertFalse(is_ocg_expansion("Legend of Blue Eyes"))

    def test_is_non_tcg_expansion(self):
        self.assertTrue(is_non_tcg_expansion("Rush Duel: Foo"))
        self.assertFalse(is_non_tcg_expansion("Secret Rare"))

    def test_build_exclusion_rejection_shape(self):
        row = build_exclusion_rejection(
            {"expansion_id": 5758, "expansion_name": "Rush Duel: Foo"},
            "rush_duel",
        )
        self.assertEqual(row["expansion_id"], 5758)
        self.assertEqual(row["rejection_reason"], REJECTION_REASON_NOT_TCG)
        self.assertEqual(row["exclusion_category"], "rush_duel")
        self.assertEqual(row["total_attempts"], 0)
        self.assertEqual(row["attempts_detail"], [])

    def test_partition_expansions(self):
        rows = [
            {"expansion_id": 1, "expansion_name": "TCG Set"},
            {"expansion_id": 5758, "expansion_name": "Rush Duel: Foo"},
        ]
        tcg, rejected = partition_expansions(rows)
        self.assertEqual(len(tcg), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["exclusion_category"], "rush_duel")
