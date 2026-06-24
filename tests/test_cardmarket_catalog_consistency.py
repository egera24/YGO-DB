"""Tests for Cardmarket job-2 catalog coverage audit."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ygo_app.cardmarket.catalog_consistency import (
    CardListCoverageError,
    audit_card_list_coverage,
    gap_expansion_ids,
    purge_orphan_card_rows,
)
from ygo_app.jobs.cardmarket_catalog_status import _run


EXPANSIONS = [
    {"expansion_id": 100, "expansion_name": "Alpha", "expansion_code": "ALP", "total_number_of_cards": 1},
    {"expansion_id": 200, "expansion_name": "Beta", "total_number_of_cards": 0},
    {"expansion_id": 300, "expansion_name": "Gamma"},
]

CARDS = [
    {
        "expansion_id": 100,
        "expansion_name": "Alpha",
        "expansion_code": "ALP",
        "card_id": 1,
        "card_name": "Card One",
        "card_number": "001",
        "card_rarity": "Common",
        "card_url": "https://example.com/1",
    },
]


class TestAuditCardListCoverage(unittest.TestCase):
    def test_fully_accounted_ok(self):
        report = audit_card_list_coverage(
            expansion_list=[EXPANSIONS[0]],
            card_list=CARDS,
            empty_expansions=[],
            rejected_expansions=[],
        )
        self.assertTrue(report.ok)
        self.assertEqual(report.has_cards, 1)
        self.assertEqual(report.issues, [])

    def test_never_scraped(self):
        report = audit_card_list_coverage(
            expansion_list=[EXPANSIONS[2]],
            card_list=[],
            empty_expansions=[],
            rejected_expansions=[],
        )
        self.assertFalse(report.ok)
        self.assertEqual(report.never_scraped, 1)
        self.assertEqual(report.issues[0].kind, "never_scraped")

    def test_ghost_processed(self):
        report = audit_card_list_coverage(
            expansion_list=[EXPANSIONS[1]],
            card_list=[],
            empty_expansions=[],
            rejected_expansions=[],
        )
        self.assertFalse(report.ok)
        self.assertEqual(report.ghost_processed, 1)
        self.assertEqual(report.issues[0].kind, "ghost_processed")

    def test_empty_and_rejected(self):
        report = audit_card_list_coverage(
            expansion_list=EXPANSIONS,
            card_list=CARDS,
            empty_expansions=[{"expansion_id": 200, "expansion_name": "Beta"}],
            rejected_expansions=[{"expansion_id": 300, "expansion_name": "Gamma"}],
        )
        self.assertTrue(report.ok)
        self.assertEqual(report.empty, 1)
        self.assertEqual(report.rejected_tcg, 1)

    def test_orphan_card_expansion(self):
        orphan_card = dict(CARDS[0])
        orphan_card["expansion_id"] = 9999
        orphan_card["expansion_name"] = "Orphan"
        report = audit_card_list_coverage(
            expansion_list=[EXPANSIONS[0]],
            card_list=[CARDS[0], orphan_card],
            empty_expansions=[],
            rejected_expansions=[],
        )
        self.assertFalse(report.ok)
        self.assertEqual(report.orphan_card_expansion_ids, [9999])

    def test_duplicate_card_id(self):
        duplicate = dict(CARDS[0])
        report = audit_card_list_coverage(
            expansion_list=[EXPANSIONS[0]],
            card_list=[CARDS[0], duplicate],
            empty_expansions=[],
            rejected_expansions=[],
        )
        self.assertFalse(report.ok)
        self.assertEqual(report.duplicate_card_ids, [1])

    def test_to_dict_includes_ok(self):
        report = audit_card_list_coverage(
            expansion_list=[EXPANSIONS[0]],
            card_list=CARDS,
            empty_expansions=[],
            rejected_expansions=[],
        )
        payload = report.to_dict()
        self.assertTrue(payload["ok"])

    def test_gap_expansion_ids(self):
        report = audit_card_list_coverage(
            expansion_list=EXPANSIONS,
            card_list=CARDS,
            empty_expansions=[],
            rejected_expansions=[],
        )
        gaps = gap_expansion_ids(report)
        self.assertEqual(gaps, {200, 300})

    def test_purge_orphan_card_rows(self):
        orphan = dict(CARDS[0])
        orphan["expansion_id"] = 9999
        cleaned, removed = purge_orphan_card_rows(
            [CARDS[0], orphan],
            [EXPANSIONS[0]],
        )
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(removed, [9999])


class TestCatalogStatusStrict(unittest.TestCase):
    def _write_catalog(self, catalog: Path, *, expansions, cards, empty=None, rejected=None):
        (catalog / "cardmarket_expansion_list.json").write_text(
            json.dumps(expansions),
            encoding="utf-8",
        )
        (catalog / "cardmarket_card_list.json").write_text(
            json.dumps(cards),
            encoding="utf-8",
        )
        (catalog / "cardmarket_empty_expansions.json").write_text(
            json.dumps(empty or []),
            encoding="utf-8",
        )
        (catalog / "cardmarket_rejected_expansions.json").write_text(
            json.dumps(rejected or []),
            encoding="utf-8",
        )

    def test_strict_passes_when_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp)
            self._write_catalog(catalog, expansions=[EXPANSIONS[0]], cards=CARDS)
            code = _run(["--catalog-dir", str(catalog), "--strict"])
            self.assertEqual(code, 0)

    def test_strict_fails_on_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp)
            self._write_catalog(catalog, expansions=EXPANSIONS, cards=CARDS)
            code = _run(["--catalog-dir", str(catalog), "--strict"])
            self.assertEqual(code, 1)

    def test_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp)
            self._write_catalog(catalog, expansions=[EXPANSIONS[0]], cards=CARDS)
            import io
            from contextlib import redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf):
                code = _run(["--catalog-dir", str(catalog), "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(buf.getvalue())
            self.assertTrue(payload["ok"])


class TestCardListCoverageError(unittest.TestCase):
    def test_is_exception(self):
        self.assertIsInstance(CardListCoverageError("x"), Exception)


if __name__ == "__main__":
    unittest.main()
