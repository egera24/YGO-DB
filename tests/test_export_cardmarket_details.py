"""Tests for joining Cardmarket details with Yugipedia catalog."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ygo_app.cardmarket.details_export import build_details_index, export_prices_from_details


DETAIL_ROW = {
    "card_data": {
        "card_id": 260903,
        "card_name": "Number 20: Giga-Brilliant",
        "card_rarity": "Ultimate Rare",
        "card_number": "V02",
        "card_set_number": "ZTIN-ENV02",
    },
    "expansion_data": {
        "expansion_id": 1433,
        "expansion_name": "2013 Zexal Collection Tin",
        "expansion_code": "ZTIN",
    },
    "price_data": {
        "url": "https://www.cardmarket.com/en/YuGiOh/Products/Singles/x/y",
        "low_price": 0.03,
        "trend_price": 1.35,
        "avg_30_price": 1.26,
        "avg_7_price": 1.33,
        "avg_1_price": 0.8,
        "price_date": "2025-10-27",
        "currency": "EUR",
    },
}

CATALOG = [
    {
        "id": "12345678",
        "name": "Test Card",
        "card_sets": [
            {
                "set_code": "ZTIN-ENV02",
                "set_rarity": "Ultimate Rare",
                "set_rarity_code": "UtR",
            }
        ],
    }
]


class TestExportCardmarketDetails(unittest.TestCase):
    def test_build_details_index(self):
        index = build_details_index([DETAIL_ROW])
        self.assertIn(("ZTIN-ENV02", "ultimate rare"), index)
        self.assertEqual(index[("ZTIN-ENV02", "ultimate rare")]["low_price"], 0.03)

    def test_export_prices_from_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            details_path = tmp_path / "details.json"
            catalog_path = tmp_path / "catalog.json"
            output_path = tmp_path / "prices.json"
            details_path.write_text(json.dumps([DETAIL_ROW]), encoding="utf-8")
            catalog_path.write_text(json.dumps(CATALOG), encoding="utf-8")

            stats = export_prices_from_details(
                details_path=details_path,
                catalog_path=catalog_path,
                output_path=output_path,
            )
            self.assertEqual(stats["matched"], 1)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["stats"]["with_prices"], 1)
            row = payload["prices"][0]
            self.assertEqual(row["set_code"], "ZTIN-ENV02")
            self.assertEqual(row["rarity_code"], "UtR")
            self.assertEqual(row["low_price"], 0.03)
