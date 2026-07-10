"""Tests for incremental revision skip during details scrape."""

import unittest
from unittest.mock import MagicMock, patch

from ygo_app.yugipedia.details import _filter_pending_with_revisions


class TestRevisionSkip(unittest.TestCase):
    @patch("ygo_app.yugipedia.details.fetch_current_revisions")
    def test_skips_unchanged_cards_with_supplements(self, mock_revs):
        mock_revs.return_value = {
            "Dark Magician": {"revid": 100, "touched": "2024-01-01T00:00:00Z"},
            "Blue-Eyes White Dragon": {"revid": 200, "touched": "2024-01-01T00:00:00Z"},
        }
        slice_cards = [
            {
                "password": "46986414",
                "name": "Dark Magician",
                "url": "https://yugipedia.com/wiki/Dark_Magician",
            },
            {
                "password": "89631139",
                "name": "Blue-Eyes White Dragon",
                "url": "https://yugipedia.com/wiki/Blue-Eyes_White_Dragon",
            },
        ]
        existing_by_key = {
            "46986414": {
                "id": "46986414",
                "page_revid": 100,
                "errata": [],
                "tips": [],
            },
            "89631139": {
                "id": "89631139",
                "page_revid": 200,
                "errata": [],
                "tips": [],
            },
        }
        pending, skipped = _filter_pending_with_revisions(
            slice_cards,
            existing_by_key=existing_by_key,
            resume=True,
            session=MagicMock(),
        )
        self.assertEqual(skipped, 2)
        self.assertEqual(pending, [])

    @patch("ygo_app.yugipedia.details.fetch_current_revisions")
    def test_requeues_when_revid_changed(self, mock_revs):
        mock_revs.return_value = {
            "Dark Magician": {"revid": 101, "touched": "2024-02-01T00:00:00Z"},
        }
        slice_cards = [
            {
                "password": "46986414",
                "name": "Dark Magician",
                "url": "https://yugipedia.com/wiki/Dark_Magician",
            },
        ]
        existing_by_key = {
            "46986414": {
                "id": "46986414",
                "page_revid": 100,
                "errata": [],
                "tips": [],
            },
        }
        pending, skipped = _filter_pending_with_revisions(
            slice_cards,
            existing_by_key=existing_by_key,
            resume=True,
            session=MagicMock(),
        )
        self.assertEqual(skipped, 0)
        self.assertEqual(len(pending), 1)

    @patch("ygo_app.yugipedia.details.fetch_current_revisions")
    def test_requeues_when_supplements_incomplete(self, mock_revs):
        mock_revs.return_value = {
            "Dark Magician": {"revid": 100, "touched": "2024-01-01T00:00:00Z"},
        }
        slice_cards = [
            {
                "password": "46986414",
                "name": "Dark Magician",
                "url": "https://yugipedia.com/wiki/Dark_Magician",
            },
        ]
        existing_by_key = {
            "46986414": {
                "id": "46986414",
                "page_revid": 100,
                "errata": [],
            },
        }
        pending, skipped = _filter_pending_with_revisions(
            slice_cards,
            existing_by_key=existing_by_key,
            resume=True,
            session=MagicMock(),
        )
        self.assertEqual(skipped, 0)
        self.assertEqual(len(pending), 1)


if __name__ == "__main__":
    unittest.main()
