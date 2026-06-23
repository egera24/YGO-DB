"""Tests for Cardmarket incremental diff, merge, and validation."""

from __future__ import annotations

import unittest

from ygo_app.cardmarket.incremental import (
    IncrementalConflictError,
    diff_expansions,
    find_duplicate_match_keys,
    merge_card_details,
    merge_card_lists,
    merge_expansion_lists,
    raise_on_conflicts,
    validate_catalog_integrity,
)
from ygo_app.cardmarket.details_export import validate_export_match_keys


def _expansion(eid: int, name: str, code: str | None = None) -> dict:
    row = {"expansion_id": eid, "expansion_name": name, "expansion_code": code}
    return row


def _card(
    *,
    card_id: int,
    expansion_id: int,
    code: str = "LOB",
    number: str = "001",
    rarity: str = "Ultra Rare",
) -> dict:
    return {
        "expansion_id": expansion_id,
        "expansion_name": "Test",
        "expansion_code": code,
        "card_id": card_id,
        "card_name": "Dark Magician",
        "card_number": number,
        "card_rarity": rarity,
        "card_url": "https://www.cardmarket.com/en/YuGiOh/Products/Singles/x/y",
    }


def _detail(card_id: int, code: str = "LOB", number: str = "001", rarity: str = "Ultra Rare") -> dict:
    return {
        "card_data": {
            "card_id": card_id,
            "card_name": "Dark Magician",
            "card_rarity": rarity,
            "card_number": number,
            "card_set_number": f"{code}-EN{number}",
        },
        "expansion_data": {
            "expansion_id": 1,
            "expansion_name": "Test",
            "expansion_code": code,
        },
        "price_data": {
            "url": "https://www.cardmarket.com/en/YuGiOh/Products/Singles/x/y",
            "low_price": 1.0,
            "trend_price": 2.0,
            "avg_30_price": 1.5,
            "avg_7_price": 1.6,
            "avg_1_price": 1.4,
            "price_date": "2026-01-01",
            "currency": "EUR",
        },
    }


class TestDiffExpansions(unittest.TestCase):
    def test_new_expansion_only(self):
        stored = [_expansion(1, "Old Set")]
        live = [_expansion(1, "Old Set"), _expansion(2, "Brand New Set")]
        plan = diff_expansions(stored, live)
        self.assertEqual(plan.new_ids, {2})
        self.assertEqual(plan.scrape_ids, {2})
        self.assertEqual(plan.removed_ids, set())

    def test_migration_by_name(self):
        stored = [_expansion(100, "Super Set", "SSP")]
        live = [_expansion(200, "Super Set", None)]
        plan = diff_expansions(stored, live, seed_codes={100: "SSP"})
        self.assertEqual(len(plan.migrations), 1)
        self.assertEqual(plan.migrations[0].old_id, 100)
        self.assertEqual(plan.migrations[0].new_id, 200)
        self.assertEqual(plan.scrape_ids, {200})
        self.assertEqual(plan.orphaned_ids, set())

    def test_migration_by_code(self):
        stored = [_expansion(100, "Old Name", "ABC")]
        live = [_expansion(200, "Renamed", None)]
        plan = diff_expansions(stored, live, seed_codes={200: "ABC"})
        self.assertEqual(len(plan.migrations), 1)
        self.assertEqual(plan.migrations[0].new_id, 200)

    def test_ambiguous_migration_by_name(self):
        stored = [_expansion(100, "Gone Set")]
        live = [_expansion(201, "Gone Set"), _expansion(202, "Gone Set")]
        plan = diff_expansions(stored, live)
        self.assertTrue(plan.ambiguous_migrations)
        self.assertEqual(len(plan.migrations), 0)

    def test_orphaned_removed_id(self):
        stored = [_expansion(1, "A"), _expansion(2, "B")]
        live = [_expansion(1, "A")]
        plan = diff_expansions(stored, live)
        self.assertEqual(plan.orphaned_ids, {2})


class TestMergeCardLists(unittest.TestCase):
    def test_append_new_cards(self):
        existing = [_card(card_id=1, expansion_id=10)]
        incoming = [_card(card_id=2, expansion_id=20, number="002")]
        merged, conflicts = merge_card_lists(existing, incoming)
        self.assertEqual(conflicts, [])
        self.assertEqual({c["card_id"] for c in merged}, {1, 2})

    def test_purge_on_migration(self):
        existing = [
            _card(card_id=1, expansion_id=100),
            _card(card_id=2, expansion_id=200, number="002"),
        ]
        incoming = [_card(card_id=3, expansion_id=200, number="003")]
        merged, conflicts = merge_card_lists(existing, incoming, purge_expansion_ids={100})
        self.assertEqual(conflicts, [])
        self.assertEqual({c["card_id"] for c in merged}, {2, 3})

    def test_reject_duplicate_card_id(self):
        existing = [_card(card_id=1, expansion_id=10)]
        incoming = [_card(card_id=1, expansion_id=20)]
        _, conflicts = merge_card_lists(existing, incoming)
        self.assertEqual(conflicts[0]["type"], "duplicate_card_id")

    def test_reject_duplicate_printing_key(self):
        existing = [_card(card_id=1, expansion_id=10)]
        incoming = [_card(card_id=2, expansion_id=20)]
        _, conflicts = merge_card_lists(existing, incoming)
        self.assertEqual(conflicts[0]["type"], "duplicate_printing_key")


class TestMergeCardDetails(unittest.TestCase):
    def test_upsert_by_card_id(self):
        existing = [_detail(1, number="001")]
        incoming = [_detail(2, number="002")]
        merged, conflicts = merge_card_details(existing, incoming)
        self.assertEqual(conflicts, [])
        self.assertEqual(len(merged), 2)

    def test_purge_card_ids(self):
        existing = [_detail(1), _detail(2, number="002")]
        merged, conflicts = merge_card_details(existing, [], purge_card_ids={1})
        self.assertEqual(conflicts, [])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["card_data"]["card_id"], 2)

    def test_reject_duplicate_match_key(self):
        existing = [_detail(1)]
        incoming = [_detail(2)]
        _, conflicts = merge_card_details(existing, incoming)
        self.assertEqual(conflicts[0]["type"], "duplicate_match_key")


class TestValidation(unittest.TestCase):
    def test_validate_catalog_integrity_ok(self):
        cards = [_card(card_id=1, expansion_id=10)]
        details = [_detail(1)]
        self.assertEqual(validate_catalog_integrity(cards=cards, details=details), [])

    def test_raise_on_conflicts(self):
        with self.assertRaises(IncrementalConflictError):
            raise_on_conflicts([{"type": "duplicate_card_id", "card_id": 1}])

    def test_validate_export_match_keys(self):
        with self.assertRaises(IncrementalConflictError):
            validate_export_match_keys([_detail(1), _detail(2)])

    def test_find_duplicate_match_keys(self):
        conflicts = find_duplicate_match_keys([_detail(1), _detail(2)])
        self.assertEqual(len(conflicts), 1)


class TestMergeExpansionLists(unittest.TestCase):
    def test_upsert_preserves_code(self):
        stored = [_expansion(1, "Set A", "ABC")]
        live = [_expansion(1, "Set A Renamed", None)]
        merged = merge_expansion_lists(stored, live)
        self.assertEqual(merged[0]["expansion_code"], "ABC")
        self.assertEqual(merged[0]["expansion_name"], "Set A Renamed")


if __name__ == "__main__":
    unittest.main()
