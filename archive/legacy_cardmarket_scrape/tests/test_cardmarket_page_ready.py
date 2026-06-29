"""Tests for Cardmarket page-ready / blocked detection."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from ygo_app.cardmarket.browser_client import (
    _cardmarket_page_ready,
    _detail_page_url,
    _page_is_blocked,
)


class TestPageBlocked(unittest.TestCase):
    def _page_without_cookies(self) -> MagicMock:
        page = MagicMock()
        page.locator.return_value.first.is_visible.return_value = False
        page.get_by_role.return_value.is_visible.return_value = False
        return page

    def test_homepage_html_not_blocked_without_prices(self):
        page = self._page_without_cookies()
        html = (
            '<html><body><input placeholder="Search Cardmarket">'
            "<h2>Trends</h2><a href='/en/YuGiOh/Products/Singles/x'>Card</a>"
            "</body></html>"
        )
        self.assertFalse(_page_is_blocked(html, page, require_prices=False))

    def test_verification_page_is_blocked(self):
        page = self._page_without_cookies()
        html = "<html><body>Performing security verification</body></html>"
        self.assertTrue(_page_is_blocked(html, page, require_prices=False))

    def test_detail_page_without_prices_is_blocked(self):
        page = self._page_without_cookies()
        html = "<html><body>Some card page without prices</body></html>"
        self.assertTrue(_page_is_blocked(html, page, require_prices=True))

    def test_detail_page_with_prices_not_blocked(self):
        page = self._page_without_cookies()
        html = "<html><body><dt>Price Trend</dt><dd>1,00 €</dd></body></html>"
        self.assertFalse(_page_is_blocked(html, page, require_prices=True))

    def test_detail_url_detection(self):
        self.assertTrue(
            _detail_page_url(
                "https://www.cardmarket.com/en/YuGiOh/Products/Singles/Set/Card"
            )
        )
        self.assertFalse(_detail_page_url("https://www.cardmarket.com/en/YuGiOh"))


if __name__ == "__main__":
    unittest.main()
