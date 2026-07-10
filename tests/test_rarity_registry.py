"""Unit tests for ygo_app.rarity_registry."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ygo_app.rarity_registry import (
    clear_rarity_registry_cache,
    rarity_code_for_name,
    rarity_match_variants,
    resolve_rarity,
    variants_for_printing,
)


class TestRarityRegistry(unittest.TestCase):
    def tearDown(self):
        clear_rarity_registry_cache()

    def test_resolve_short_print_aliases(self):
        for raw in ("SP", "(SP)", "Short Print", "(Short Print)", "sp"):
            resolved = resolve_rarity(raw)
            self.assertIsNotNone(resolved, raw)
            assert resolved is not None
            self.assertEqual(resolved.name, "Short Print")
            self.assertEqual(resolved.code, "SP")
            self.assertEqual(resolved.normalized_code, "(SP)")

    def test_resolve_quarter_century_aliases(self):
        for raw in ("QCSR", "QCScR", "QCR", "Quarter Century Secret Rare"):
            resolved = resolve_rarity(raw)
            self.assertIsNotNone(resolved, raw)
            assert resolved is not None
            self.assertEqual(resolved.name, "Quarter Century Secret Rare")
            self.assertEqual(resolved.normalized_code, "(QCSR)")

    def test_pscr_and_plscr_are_distinct(self):
        pscr = resolve_rarity("PScR")
        plscr = resolve_rarity("PlScR")
        self.assertIsNotNone(pscr)
        self.assertIsNotNone(plscr)
        assert pscr is not None and plscr is not None
        self.assertEqual(pscr.name, "Prismatic Secret Rare")
        self.assertEqual(plscr.name, "Platinum Secret Rare")
        self.assertNotEqual(pscr.normalized_code, plscr.normalized_code)

    def test_unknown_rarity_returns_none(self):
        self.assertIsNone(resolve_rarity("ZZZ"))
        self.assertIsNone(resolve_rarity(""))

    def test_rarity_match_variants_prefers_canonical_first(self):
        variants = rarity_match_variants("SP")
        self.assertEqual(variants[0], "(SP)")
        self.assertIn("(Short Print)", variants)

    def test_variants_for_printing_with_label_only(self):
        variants = variants_for_printing("(Short Print)", "Short Print")
        self.assertIn("(SP)", variants)
        self.assertIn("(Short Print)", variants)

    def test_rarity_code_for_name(self):
        self.assertEqual(rarity_code_for_name("Short Print"), "SP")
        self.assertEqual(rarity_code_for_name("Unknown Foo"), "")

    def test_json_alias_override_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            alias_file = Path(tmp) / "rarity_aliases.json"
            alias_file.write_text(
                json.dumps(
                    {
                        "aliases": [
                            {
                                "alias": "PortalX",
                                "canonical_name": "Duel Terminal Ultra Parallel Rare",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with patch("ygo_app.rarity_registry._ALIASES_JSON", alias_file):
                clear_rarity_registry_cache()
                resolved = resolve_rarity("PortalX")
                self.assertIsNotNone(resolved)
                assert resolved is not None
                self.assertEqual(
                    resolved.name, "Duel Terminal Ultra Parallel Rare"
                )
                self.assertEqual(resolved.code, "DUPR")


if __name__ == "__main__":
    unittest.main()
