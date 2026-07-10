"""Tests for Yugipedia catalog import CLI helpers."""

import unittest

from ygo_app.jobs.import_catalog_yugipedia import resolve_min_cards


class TestResolveMinCards(unittest.TestCase):
    def test_full_catalog_default(self) -> None:
        self.assertEqual(resolve_min_cards(limit=None, min_cards=None), 1000)

    def test_limit_uses_eighty_percent_floor(self) -> None:
        self.assertEqual(resolve_min_cards(limit=500, min_cards=None), 400)

    def test_explicit_min_cards_wins(self) -> None:
        self.assertEqual(resolve_min_cards(limit=500, min_cards=450), 450)


if __name__ == "__main__":
    unittest.main()
