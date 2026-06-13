"""Import Cardmarket price export JSON into printing_market_prices."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.cardmarket.export_schema import SCHEMA_VERSION, build_export_payload, load_export, save_export
from ygo_app.jobs.import_cardmarket_prices import import_prices_from_payload
from ygo_app.models import Base, Card, Printing, PrintingMarketPrice
from ygo_app.services import get_card_detail


def _sqlite_engine(path: str):
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return eng


class TestImportCardmarketPrices(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.engine = _sqlite_engine(self.tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

        card = Card(id=85087012, name="Card Trooper")
        self.session.add(card)
        self.session.add(
            Printing(
                card_id=card.id,
                set_code="ANPR-ENSE1",
                set_rarity="Super Rare",
                set_rarity_code="SR",
                set_name="Ancient Prophecy",
            )
        )
        self.session.commit()

        self.export_dir = Path(tempfile.mkdtemp())
        self.export_path = self.export_dir / "cardmarket_prices.json"

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _write_fixture(self, extra_rows: list[dict] | None = None) -> dict:
        rows = [
            {
                "set_code": "ANPR-ENSE1",
                "rarity_code": "SR",
                "cardmarket_product_id": 999,
                "cardmarket_url": "https://example.com/card",
                "low_price": 0.5,
                "avg_price": 0.75,
                "trend_price": 1.2,
                "discovery_status": "matched",
            }
        ]
        if extra_rows:
            rows.extend(extra_rows)
        payload = build_export_payload(rows)
        save_export(self.export_path, payload)
        return payload

    def test_schema_version(self):
        payload = self._write_fixture()
        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)

    def test_load_export_validates(self):
        self._write_fixture()
        loaded = load_export(self.export_path)
        self.assertEqual(len(loaded["prices"]), 1)

    def test_import_upserts_rows(self):
        self._write_fixture()
        payload = load_export(self.export_path)
        stats = import_prices_from_payload(self.session, payload)
        self.assertEqual(stats["inserted"], 1)
        self.assertEqual(stats["updated"], 0)

        row = self.session.get(PrintingMarketPrice, {"set_code": "ANPR-ENSE1", "rarity_code": "SR"})
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row.low_price, 0.5)
        self.assertAlmostEqual(row.trend_price, 1.2)

    def test_import_updates_existing(self):
        self._write_fixture()
        payload = load_export(self.export_path)
        import_prices_from_payload(self.session, payload)
        payload["prices"][0]["low_price"] = 0.9
        save_export(self.export_path, payload)
        stats = import_prices_from_payload(self.session, load_export(self.export_path))
        self.assertEqual(stats["updated"], 1)
        row = self.session.get(PrintingMarketPrice, {"set_code": "ANPR-ENSE1", "rarity_code": "SR"})
        self.assertAlmostEqual(row.low_price, 0.9)

    def test_get_card_detail_shows_imported_prices(self):
        self._write_fixture()
        import_prices_from_payload(self.session, load_export(self.export_path))
        detail = get_card_detail(self.session, 85087012, None)
        self.assertIsNotNone(detail)
        p = detail.printings[0]
        self.assertAlmostEqual(p.low_price, 0.5)

    def test_rejects_invalid_schema(self):
        self.export_path.write_text(json.dumps({"schema_version": 99, "prices": []}), encoding="utf-8")
        with self.assertRaises(Exception):
            load_export(self.export_path)


if __name__ == "__main__":
    unittest.main()
