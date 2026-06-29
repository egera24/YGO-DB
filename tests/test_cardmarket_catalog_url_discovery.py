"""Discover Cardmarket S3 URLs from saved HTML fixtures."""

from __future__ import annotations

import unittest
from pathlib import Path

from ygo_app.cardmarket.catalog.download import discover_urls_from_html, resolve_download_urls


class TestCardmarketCatalogUrlDiscovery(unittest.TestCase):
    def test_discovers_urls_from_product_catalog_html(self):
        html_path = (
            Path(__file__).resolve().parents[1]
            / "DO NOT DELETE"
            / "cardmarket_product_catalog_html_code.html"
        )
        if not html_path.is_file():
            self.skipTest("HTML fixture not available")
        html = html_path.read_text(encoding="utf-8", errors="replace")
        urls = discover_urls_from_html(html)
        self.assertIn("singles", urls)
        self.assertIn("nonsingles", urls)
        self.assertIn("products_singles_3.json", urls["singles"])
        self.assertIn("products_nonsingles_3.json", urls["nonsingles"])

    def test_discovers_price_guide_from_html(self):
        html = (
            '<a href="https://downloads.s3.cardmarket.com/productCatalog/priceGuide/'
            'price_guide_3.json">Price Guide</a>'
        )
        urls = discover_urls_from_html(html)
        self.assertIn("price_guide", urls)
        self.assertIn("price_guide_3.json", urls["price_guide"])

    def test_resolve_falls_back_to_defaults(self):
        urls = resolve_download_urls(None)
        self.assertIn("singles", urls)
        self.assertIn("nonsingles", urls)
        self.assertIn("price_guide", urls)


if __name__ == "__main__":
    unittest.main()
