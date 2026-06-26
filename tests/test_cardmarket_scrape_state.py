"""Tests for scrape_state helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ygo_app.cardmarket.card_list_consistency import (
    CardListConsistencyError,
    assert_no_seq_gaps,
)
from ygo_app.cardmarket.scrape_state import (
    assign_expansion_seq,
    rollback_cards_after_seq,
)


class TestScrapeState(unittest.TestCase):
    def test_assign_expansion_seq(self):
        rows = assign_expansion_seq(
            [{"expansion_id": 10, "expansion_name": "B"}, {"expansion_id": 5, "expansion_name": "A"}]
        )
        self.assertEqual([r["seq"] for r in rows], [1, 2])
        self.assertEqual(rows[0]["expansion_id"], 5)

    def test_rollback_cards_after_seq(self):
        cards = [
            {"expansion_seq": 1, "card_id": 1},
            {"expansion_seq": 2, "card_id": 2},
            {"expansion_seq": 3, "card_id": 3},
        ]
        rolled = rollback_cards_after_seq(cards, 1)
        self.assertEqual(len(rolled), 1)

    def test_seq_gap_raises(self):
        with self.assertRaises(CardListConsistencyError):
            assert_no_seq_gaps(
                last_completed_seq=2,
                cards=[{"expansion_seq": 1, "card_id": 1}],
                empty_expansions=[],
                rejected_expansions=[],
            )


if __name__ == "__main__":
    unittest.main()
