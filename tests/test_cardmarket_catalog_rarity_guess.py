"""Rarity assignment by Cardmarket price ordering."""

from __future__ import annotations

import unittest

from ygo_app.cardmarket.catalog.errors import AmbiguousPriceOrderError, PrintingCountMismatchError
from ygo_app.cardmarket.catalog.rarity_guess import (
    CmPricedProduct,
    YugipediaPrintingRef,
    assign_rarities_by_price,
)


class TestCardmarketCatalogRarityGuess(unittest.TestCase):
    def test_assigns_lowest_price_to_lowest_rarity_rank(self):
        cm = [
            CmPricedProduct(1, "Blue-Eyes Toon Dragon", 6424, 102060, 1.95, 6.75, None),
            CmPricedProduct(2, "Blue-Eyes Toon Dragon", 6424, 102060, 2.95, 7.95, None),
            CmPricedProduct(3, "Blue-Eyes Toon Dragon", 6424, 102060, 9.9, 9.9, None),
        ]
        yg = [
            YugipediaPrintingRef("RA05-EN001", "SR", "Super Rare", "Blue-Eyes Toon Dragon", 1, 10),
            YugipediaPrintingRef("RA05-EN001", "UR", "Ultra Rare", "Blue-Eyes Toon Dragon", 1, 18),
            YugipediaPrintingRef("RA05-EN001", "ScR", "Secret Rare", "Blue-Eyes Toon Dragon", 1, 23),
        ]
        pairs = assign_rarities_by_price(
            set_code="RA05",
            card_name="Blue-Eyes Toon Dragon",
            cm_products=cm,
            yugipedia_printings=yg,
        )
        self.assertEqual(pairs[0][0].rarity_code, "SR")
        self.assertEqual(pairs[0][1].id_product, 1)
        self.assertEqual(pairs[2][0].rarity_code, "ScR")
        self.assertEqual(pairs[2][1].id_product, 3)

    def test_raises_on_count_mismatch(self):
        cm = [
            CmPricedProduct(1, "Card", 1, 1, 1.0, 1.0, None),
        ]
        yg = [
            YugipediaPrintingRef("X-EN001", "C", "Common", "Card", 1, 1),
            YugipediaPrintingRef("X-EN001", "UR", "Ultra Rare", "Card", 1, 18),
        ]
        with self.assertRaises(PrintingCountMismatchError):
            assign_rarities_by_price(
                set_code="X",
                card_name="Card",
                cm_products=cm,
                yugipedia_printings=yg,
            )

    def test_raises_on_tied_prices(self):
        cm = [
            CmPricedProduct(1, "Card", 1, 1, 1.0, 1.0, None),
            CmPricedProduct(2, "Card", 1, 1, 1.0, 1.0, None),
        ]
        yg = [
            YugipediaPrintingRef("X-EN001", "C", "Common", "Card", 1, 1),
            YugipediaPrintingRef("X-EN001", "UR", "Ultra Rare", "Card", 1, 18),
        ]
        with self.assertRaises(AmbiguousPriceOrderError):
            assign_rarities_by_price(
                set_code="X",
                card_name="Card",
                cm_products=cm,
                yugipedia_printings=yg,
            )


if __name__ == "__main__":
    unittest.main()
