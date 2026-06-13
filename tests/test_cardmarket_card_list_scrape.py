"""Tests for Cardmarket card list HTML parsing."""

from __future__ import annotations

import unittest

from ygo_app.cardmarket.product_list import (
    extract_cards_from_html,
    is_only_sealed_products,
    is_product_page_redirect,
)


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


class TestCardListParsing(unittest.TestCase):
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
