"""Tests for Cardmarket checkpoint builders and resolvers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ygo_app.cardmarket.checkpoints import (
    build_card_details_checkpoint,
    build_card_details_checkpoint_at_idx,
    build_card_list_checkpoint,
    build_card_list_checkpoint_at_idx,
    build_card_list_recovery_checkpoint,
    format_catalog_status_report,
    resolve_card_details_resume_index,
    resolve_card_list_checkpoint,
    resolve_card_list_recovery_start,
    resolve_card_list_resume_index,
)
from ygo_app.jobs.cardmarket_catalog_status import _run


EXPANSIONS = [
    {"expansion_id": 100, "expansion_name": "Alpha", "expansion_code": "ALP"},
    {"expansion_id": 200, "expansion_name": "Beta"},
    {"expansion_id": 300, "expansion_name": "Gamma", "expansion_code": "GAM"},
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
    {
        "expansion_id": 200,
        "expansion_name": "Beta",
        "expansion_code": "BET",
        "card_id": 2,
        "card_name": "Card Two",
        "card_number": "002",
        "card_rarity": "Rare",
        "card_url": "https://example.com/2",
    },
]


class TestCardListCheckpointBuilders(unittest.TestCase):
    def test_build_card_list_checkpoint_includes_legacy_and_enriched_fields(self):
        payload = build_card_list_checkpoint(
            expansion=EXPANSIONS[1],
            idx=1,
            total=3,
            expansions=EXPANSIONS,
        )
        self.assertEqual(payload["last_expansion_idx"], 1)
        self.assertEqual(payload["last_expansion_id"], 200)
        self.assertEqual(payload["last_expansion_name"], "Beta")
        self.assertNotIn("last_expansion_code", payload)
        self.assertIn("saved_at", payload)
        self.assertEqual(payload["progress"]["remaining"], 1)
        self.assertEqual(payload["next_expansion"]["expansion_id"], 300)
        self.assertEqual(payload["next_expansion"]["expansion_code"], "GAM")

    def test_build_card_list_checkpoint_at_idx_negative(self):
        payload = build_card_list_checkpoint_at_idx(EXPANSIONS, -1)
        self.assertEqual(payload["last_expansion_idx"], -1)
        self.assertIn("saved_at", payload)

    def test_build_card_list_recovery_checkpoint(self):
        rejection = {"expansion_id": 200, "expansion_name": "Beta"}
        payload = build_card_list_recovery_checkpoint(rejection=rejection, idx=0, total=2)
        self.assertEqual(payload["last_processed"], 0)
        self.assertEqual(payload["last_expansion_id"], 200)
        self.assertEqual(payload["progress"]["remaining"], 1)


class TestCardDetailsCheckpointBuilders(unittest.TestCase):
    def test_build_card_details_checkpoint_includes_card_and_expansion(self):
        payload = build_card_details_checkpoint(
            card=CARDS[0],
            idx=0,
            total=2,
            phase1_complete=False,
            cards=CARDS,
        )
        self.assertEqual(payload["last_processed_index"], 0)
        self.assertEqual(payload["last_card_id"], 1)
        self.assertEqual(payload["last_card_name"], "Card One")
        self.assertEqual(payload["last_expansion_id"], 100)
        self.assertFalse(payload["phase1_complete"])
        self.assertEqual(payload["next_card"]["card_id"], 2)

    def test_build_card_details_checkpoint_at_idx_negative(self):
        payload = build_card_details_checkpoint_at_idx(CARDS, -1, phase1_complete=False)
        self.assertEqual(payload["last_processed_index"], -1)


class TestCheckpointResolvers(unittest.TestCase):
    def test_card_list_resume_prefers_expansion_id_when_list_order_changes(self):
        reordered = [EXPANSIONS[2], EXPANSIONS[0], EXPANSIONS[1]]
        checkpoint = {"last_expansion_idx": 0, "last_expansion_id": 200}
        self.assertEqual(resolve_card_list_resume_index(checkpoint, reordered), 3)

    def test_card_list_resume_falls_back_to_index(self):
        checkpoint = {"last_expansion_idx": 1}
        self.assertEqual(resolve_card_list_resume_index(checkpoint, EXPANSIONS), 2)

    def test_card_list_recovery_prefers_expansion_id(self):
        rejected = [
            {"expansion_id": 100, "expansion_name": "Alpha"},
            {"expansion_id": 200, "expansion_name": "Beta"},
        ]
        checkpoint = {"last_processed": 0, "last_expansion_id": 100}
        self.assertEqual(resolve_card_list_recovery_start(checkpoint, rejected), 1)

    def test_card_details_resume_prefers_card_id(self):
        reordered = [CARDS[1], CARDS[0]]
        checkpoint = {"last_processed_index": 0, "last_card_id": 1}
        self.assertEqual(resolve_card_details_resume_index(checkpoint, reordered), 2)

    def test_resolve_card_list_checkpoint_from_legacy_index(self):
        resolved = resolve_card_list_checkpoint({"last_expansion_idx": 0}, EXPANSIONS)
        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved["idx"], 0)
        self.assertEqual(resolved["expansion"]["expansion_id"], 100)
        self.assertEqual(resolved["next"]["expansion"]["expansion_id"], 200)


class TestCatalogStatusReport(unittest.TestCase):
    def test_format_catalog_status_report_smoke(self):
        report = format_catalog_status_report(
            expansion_list=EXPANSIONS,
            card_list=CARDS,
            empty_expansions=[],
            rejected_expansions=[],
            card_list_checkpoint=build_card_list_checkpoint_at_idx(EXPANSIONS, 0),
            recovery_checkpoint=None,
            card_details=[],
            card_details_rejections=[],
            card_details_checkpoint=build_card_details_checkpoint_at_idx(
                CARDS, 0, phase1_complete=False
            ),
        )
        self.assertIn("Job 1: expansion list", report)
        self.assertIn("id=100", report)
        self.assertIn("Card One", report)

    def test_status_job_with_fixture_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp)
            (catalog / "cardmarket_expansion_list.json").write_text(
                __import__("json").dumps(EXPANSIONS),
                encoding="utf-8",
            )
            (catalog / "cardmarket_card_list.json").write_text(
                __import__("json").dumps(CARDS),
                encoding="utf-8",
            )
            (catalog / "cardmarket_card_list_checkpoint.json").write_text(
                __import__("json").dumps(build_card_list_checkpoint_at_idx(EXPANSIONS, 0)),
                encoding="utf-8",
            )
            code = _run(["--catalog-dir", str(catalog)])
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
