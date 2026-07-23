"""Ensure frontend rarity badge metadata matches the Python registry."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from ygo_app.rarity_registry import list_rarity_ui_metadata

REPO_ROOT = Path(__file__).resolve().parents[1]
RARITY_BADGES_JS = REPO_ROOT / "ygo_app" / "static" / "js" / "rarity-badges.js"


def _parse_js_rarity_rows(source: str) -> list[dict]:
    match = re.search(
        r"export const RARITY_UI_ROWS = (\[[\s\S]*?\n\]);",
        source,
    )
    if not match:
        raise AssertionError("RARITY_UI_ROWS not found in rarity-badges.js")
    block = match.group(1)
    row_re = re.compile(
        r"sort_order:\s*(?P<sort_order>\d+),\s*"
        r'name:\s*"(?P<name>(?:\\.|[^"\\])*)",\s*'
        r'code:\s*"(?P<code>(?:\\.|[^"\\])*)",\s*'
        r'normalized_code:\s*"(?P<normalized_code>(?:\\.|[^"\\])*)",\s*'
        r'display:\s*"(?P<display>(?:\\.|[^"\\])*)",\s*'
        r'tone:\s*"(?P<tone>(?:\\.|[^"\\])*)"'
    )
    rows = []
    for hit in row_re.finditer(block):
        rows.append(
            {
                "sort_order": int(hit.group("sort_order")),
                "name": hit.group("name"),
                "code": hit.group("code"),
                "normalized_code": hit.group("normalized_code"),
                "display": hit.group("display"),
                "tone": hit.group("tone"),
            }
        )
    if not rows:
        raise AssertionError("No rarity rows parsed from rarity-badges.js")
    return rows


class TestRarityUiSync(unittest.TestCase):
    def test_js_metadata_matches_python_registry(self):
        source = RARITY_BADGES_JS.read_text(encoding="utf-8")
        js_rows = _parse_js_rarity_rows(source)
        py_rows = list_rarity_ui_metadata()
        self.assertEqual(len(js_rows), len(py_rows))
        for js_row, py_row in zip(js_rows, py_rows, strict=True):
            self.assertEqual(js_row["sort_order"], py_row["sort_order"])
            self.assertEqual(js_row["name"], py_row["name"])
            self.assertEqual(js_row["code"], py_row["code"])
            self.assertEqual(js_row["normalized_code"], py_row["normalized_code"])
            self.assertEqual(js_row["display"], py_row["display"])
            self.assertEqual(js_row["tone"], py_row["tone"])


if __name__ == "__main__":
    unittest.main()
