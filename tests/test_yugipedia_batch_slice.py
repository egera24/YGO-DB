"""Tests for Yugipedia passcode list batch slicing (GHA chained jobs)."""

import unittest

from ygo_app.yugipedia.details import slice_input_cards_for_batch


def _cards(n: int) -> list[dict]:
    return [{"password": f"{i:08d}", "name": f"Card {i}"} for i in range(n)]


class TestSliceInputCardsForBatch(unittest.TestCase):
    def test_partitions_full_list_without_gaps(self) -> None:
        cards = _cards(14_000)
        batch_count = 6
        seen: list[dict] = []
        for batch_index in range(batch_count):
            seen.extend(slice_input_cards_for_batch(cards, batch_index, batch_count))
        self.assertEqual(len(seen), len(cards))
        self.assertEqual([c["password"] for c in seen], [c["password"] for c in cards])

    def test_sum_of_slice_lengths_equals_total(self) -> None:
        for n in (0, 1, 5, 14_003, 100):
            cards = _cards(n)
            for batch_count in (1, 2, 6, 7):
                total = sum(
                    len(slice_input_cards_for_batch(cards, i, batch_count))
                    for i in range(batch_count)
                )
                self.assertEqual(total, n, msg=f"n={n} batch_count={batch_count}")

    def test_batch_count_one_returns_all(self) -> None:
        cards = _cards(100)
        self.assertEqual(slice_input_cards_for_batch(cards, 0, 1), cards)

    def test_last_batch_when_not_evenly_divisible(self) -> None:
        cards = _cards(14_003)
        batch_count = 6
        slices = [
            slice_input_cards_for_batch(cards, i, batch_count) for i in range(batch_count)
        ]
        self.assertEqual(len(slices[0]), 2333)
        self.assertEqual(len(slices[-1]), 2334)
        self.assertEqual(sum(len(s) for s in slices), 14_003)

    def test_invalid_batch_index_raises(self) -> None:
        cards = _cards(10)
        with self.assertRaises(ValueError):
            slice_input_cards_for_batch(cards, 6, 6)
        with self.assertRaises(ValueError):
            slice_input_cards_for_batch(cards, -1, 6)

    def test_invalid_batch_count_raises(self) -> None:
        cards = _cards(10)
        with self.assertRaises(ValueError):
            slice_input_cards_for_batch(cards, 0, 0)


if __name__ == "__main__":
    unittest.main()
