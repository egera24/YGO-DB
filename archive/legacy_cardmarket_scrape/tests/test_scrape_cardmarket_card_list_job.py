"""Tests for scrape_cardmarket_card_list job helpers."""

import unittest

from ygo_app.jobs.scrape_cardmarket_card_list import _resolve_card_list_output_path


class TestResolveCardListOutputPath(unittest.TestCase):
    def test_only_gaps_uses_state_catalog_not_today(self):
        state = {
            "run_date": "20260626",
            "card_list_file": "card_list_20260626.json",
        }
        path = _resolve_card_list_output_path(
            state=state,
            today="20260628",
            resume=False,
            only_gaps=True,
        )
        self.assertEqual(path.name, "card_list_20260626.json")

    def test_resume_uses_state_catalog(self):
        state = {
            "run_date": "20260626",
            "card_list_file": "card_list_20260626.json",
        }
        path = _resolve_card_list_output_path(
            state=state,
            today="20260628",
            resume=True,
            only_gaps=False,
        )
        self.assertEqual(path.name, "card_list_20260626.json")

    def test_full_run_without_resume_uses_today(self):
        state = {
            "run_date": "20260626",
            "card_list_file": "card_list_20260626.json",
        }
        path = _resolve_card_list_output_path(
            state=state,
            today="20260628",
            resume=False,
            only_gaps=False,
        )
        self.assertEqual(path.name, "card_list_20260628.json")


if __name__ == "__main__":
    unittest.main()
