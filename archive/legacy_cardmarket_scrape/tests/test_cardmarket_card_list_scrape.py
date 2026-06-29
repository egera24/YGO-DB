"""Tests for Cardmarket card list HTML parsing and scrape helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from ygo_app.cardmarket.card_list_scrape import _scrape_expansion_worker
from ygo_app.cardmarket.expansions import REJECTION_REASON_NOT_TCG
from ygo_app.cardmarket.http_client import ScrapeShutdown
from ygo_app.cardmarket.product_list import (
    _search_url,
    extract_cards_from_html,
    is_only_sealed_products,
    is_product_page_redirect,
)
from ygo_app.cardmarket.rejections import (
    merge_rejected_expansions,
    rejections_for_save,
)
from ygo_app.cardmarket.scrape_prompts import prompt_no_product_rows


LIST_HTML = """
<div id="productRow283144" class="row g-0">
  <div class="col-icon small">
    <a class="expansion-symbol"><span>YS15</span></a>
  </div>
  <div class="col">
    <div class="row g-0">
      <div class="col-10 col-md-8 px-2">
        <a href="/en/YuGiOh/Products/Singles/2Player-Starter-Deck-Yuya-Declan/Mirror-Force">Mirror Force</a>
      </div>
      <div class="col-md-2 d-none d-lg-flex has-content-centered"><div>D16</div></div>
      <div class="col-sm-2 d-none d-sm-flex has-content-centered">
        <svg aria-label="Super Rare"></svg>
      </div>
    </div>
  </div>
</div>
"""

EMPTY_HTML = """
<div class="table-body">
  <p class="noResults text-center">Sorry, no matches for your query</p>
</div>
"""

NO_ROWS_HTML = """
<div class="table-body">
  <div class="row g-0"><div class="col">Loading...</div></div>
</div>
"""

TEST_EXPANSION = {"expansion_id": 1651, "expansion_name": "YS15 Deck"}


class TestCardListParsing(unittest.TestCase):
    def test_search_url_uses_list_mode(self):
        url = _search_url(1651, 1)
        self.assertIn("mode=list", url)
        self.assertIn("idExpansion=1651", url)

    def test_extract_cards_from_html(self):
        cards, exp_code = extract_cards_from_html(
            LIST_HTML,
            expansion_id=1651,
            expansion_name="YS15 Deck",
        )
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["card_id"], 283144)
        self.assertEqual(cards[0]["card_name"], "Mirror Force")
        self.assertEqual(cards[0]["card_rarity"], "Super Rare")
        self.assertIn("/Products/Singles/", cards[0]["card_url"])
        self.assertEqual(exp_code, "YS15")

    def test_product_page_redirect(self):
        html = "<dt>Available items</dt><dd>5</dd>"
        self.assertTrue(is_product_page_redirect(html))
        self.assertFalse(is_product_page_redirect(LIST_HTML))

    def test_only_sealed_products(self):
        sealed = '<div id="productRow1"></div>'
        self.assertTrue(is_only_sealed_products(sealed))
        self.assertFalse(is_only_sealed_products(LIST_HTML))


class TestRejectedExpansionMerge(unittest.TestCase):
    def test_merge_preserves_prior_and_adds_session(self):
        persisted = [
            {"expansion_id": 1074, "expansion_name": "Old", "total_attempts": 1}
        ]
        session = [
            {"expansion_id": 1131, "expansion_name": "New", "total_attempts": 2}
        ]
        merged = rejections_for_save(persisted, session)
        self.assertEqual({r["expansion_id"] for r in merged}, {1074, 1131})

    def test_session_overwrites_same_expansion_id(self):
        persisted = [
            {
                "expansion_id": 1131,
                "expansion_name": "Old",
                "total_attempts": 1,
                "attempts_detail": [],
            }
        ]
        session = [
            {
                "expansion_id": 1131,
                "expansion_name": "New",
                "total_attempts": 2,
                "attempts_detail": [{"attempt": 1}],
            }
        ]
        merged = rejections_for_save(persisted, session)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["total_attempts"], 2)

    def test_recovered_ids_drop_prior_but_keep_other_rejections(self):
        persisted = [
            {"expansion_id": 1074, "expansion_name": "A", "total_attempts": 1},
            {"expansion_id": 1131, "expansion_name": "B", "total_attempts": 1},
        ]
        session = [
            {"expansion_id": 1243, "expansion_name": "C", "total_attempts": 2}
        ]
        merged = rejections_for_save(
            persisted,
            session,
            recovered_ids={1131},
        )
        self.assertEqual({r["expansion_id"] for r in merged}, {1074, 1243})

    def test_merge_rejected_expansions_sorted_by_id(self):
        merged = merge_rejected_expansions(
            [{"expansion_id": 200, "expansion_name": "B"}],
            [{"expansion_id": 100, "expansion_name": "A"}],
        )
        self.assertEqual(
            [r["expansion_id"] for r in merged],
            [100, 200],
        )


class TestNonTcgExpansionWorker(unittest.TestCase):
    def test_rush_duel_rejected_without_fetch(self):
        result = _scrape_expansion_worker(
            0,
            {
                "expansion_id": 5758,
                "expansion_name": "Rush Duel: Starter Deck Set - Yuga vs. Luke",
            },
            backend="cloudscraper",
            rate_limiter=None,
            session_pool=None,
            max_retries=1,
            retry_delay_range=(0, 0),
            is_recovery=False,
        )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["rejection_reason"], REJECTION_REASON_NOT_TCG)
        self.assertEqual(result["exclusion_category"], "rush_duel")
        self.assertEqual(result["attempts"], [])


class TestNoProductRowsPrompt(unittest.TestCase):
    def _worker_kwargs(self) -> dict:
        return {
            "backend": "cloudscraper",
            "rate_limiter": None,
            "session_pool": None,
            "max_retries": 1,
            "retry_delay_range": (0, 0),
            "is_recovery": False,
            "interactive": True,
        }

    @patch("ygo_app.cardmarket.card_list_scrape.fetch_url")
    @patch("ygo_app.cardmarket.card_list_scrape.prompt_no_product_rows", return_value="skip")
    def test_no_product_rows_skip_marks_rejected(self, _mock_prompt, mock_fetch):
        mock_fetch.return_value = (NO_ROWS_HTML, None)
        result = _scrape_expansion_worker(0, TEST_EXPANSION, **self._worker_kwargs())
        self.assertEqual(result["status"], "rejected")
        issues = result["attempts"][-1]["issues"]
        self.assertTrue(any("No product rows" in issue for issue in issues))

    @patch("ygo_app.cardmarket.card_list_scrape.fetch_url")
    @patch("ygo_app.cardmarket.card_list_scrape.prompt_no_product_rows", return_value="retry")
    def test_no_product_rows_retry_then_success(self, _mock_prompt, mock_fetch):
        mock_fetch.side_effect = [
            (NO_ROWS_HTML, None),
            (LIST_HTML, None),
            (NO_ROWS_HTML, None),
        ]
        result = _scrape_expansion_worker(0, TEST_EXPANSION, **self._worker_kwargs())
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_count"], 1)
        self.assertEqual(mock_fetch.call_count, 3)

    @patch("ygo_app.cardmarket.card_list_scrape.fetch_url")
    @patch("ygo_app.cardmarket.card_list_scrape.prompt_no_product_rows", return_value="terminate")
    def test_no_product_rows_terminate_raises(self, _mock_prompt, mock_fetch):
        mock_fetch.return_value = (NO_ROWS_HTML, None)
        with self.assertRaises(ScrapeShutdown):
            _scrape_expansion_worker(0, TEST_EXPANSION, **self._worker_kwargs())

    def test_prompt_disabled_returns_skip(self):
        action = prompt_no_product_rows(
            url=_search_url(1651, 1),
            expansion_id=1651,
            expansion_name="YS15 Deck",
            enabled=False,
        )
        self.assertEqual(action, "skip")
