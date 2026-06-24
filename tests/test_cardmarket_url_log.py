"""Cardmarket fetch URL logging labels."""

from __future__ import annotations

import unittest

from ygo_app.cardmarket.constants import BASE_URL, CARD_LIST_PROBE_URL, SEARCH_URL
from ygo_app.cardmarket.product_list import _search_url
from ygo_app.cardmarket.url_log import format_fetch_url


class TestFormatFetchUrl(unittest.TestCase):
    def test_product_search_includes_expansion_and_site(self):
        url = _search_url(1651, 1)
        label = format_fetch_url(url)
        self.assertIn("idExpansion=1651", label)
        self.assertIn("site=1", label)
        self.assertIn("mode=list", label)

    def test_distinct_expansions_differ(self):
        a = format_fetch_url(_search_url(1651, 1))
        b = format_fetch_url(_search_url(42, 1))
        self.assertNotEqual(a, b)
        self.assertIn("idExpansion=1651", a)
        self.assertIn("idExpansion=42", b)

    def test_distinct_pages_differ(self):
        page1 = format_fetch_url(_search_url(1651, 1))
        page2 = format_fetch_url(_search_url(1651, 2))
        self.assertNotEqual(page1, page2)
        self.assertIn("site=1", page1)
        self.assertIn("site=2", page2)

    def test_expansion_list_search_url(self):
        label = format_fetch_url(SEARCH_URL)
        self.assertIn("idExpansion=0", label)
        self.assertIn("perSite=1", label)
        self.assertIn("mode=list", label)

    def test_probe_url(self):
        label = format_fetch_url(CARD_LIST_PROBE_URL)
        self.assertEqual(label, "idExpansion=1 site=1 mode=list")

    def test_warmup_path(self):
        label = format_fetch_url(f"{BASE_URL}/en/YuGiOh")
        self.assertEqual(label, "/en/YuGiOh")

    def test_product_detail_path(self):
        url = (
            f"{BASE_URL}/en/YuGiOh/Products/Singles/"
            "Legend-of-Blue-Eyes-White-Dragon/Blue-Eyes-White-Dragon"
        )
        label = format_fetch_url(url)
        self.assertEqual(
            label,
            "/en/YuGiOh/Products/Singles/Legend-of-Blue-Eyes-White-Dragon/Blue-Eyes-White-Dragon",
        )

    def test_unknown_url_fallback(self):
        url = "not-a-valid-url"
        self.assertEqual(format_fetch_url(url), url)


if __name__ == "__main__":
    unittest.main()
