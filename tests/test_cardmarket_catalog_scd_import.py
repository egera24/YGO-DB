"""SCD Type 2 import for Cardmarket catalog prices."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.cardmarket.export_schema import build_export_payload, save_export
from ygo_app.cardmarket.market_prices import get_current_market_price, load_all_current_market_prices
from ygo_app.jobs.import_cardmarket_prices import (
    compute_import_fingerprint,
    import_prices_from_payload,
)
from ygo_app.models import Base, PrintingMarketPrice


def _sqlite_engine(path: str):
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return eng


class TestCardmarketCatalogScdImport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.engine = _sqlite_engine(self.tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _payload(self, low_price: float = 0.5) -> dict:
        return build_export_payload(
            [
                {
                    "set_code": "ANPR-ENSE1",
                    "rarity_code": "SR",
                    "low_price": low_price,
                    "avg_price": 0.75,
                    "trend_price": 1.2,
                    "discovery_status": "matched",
                }
            ]
        )

    def test_insert_creates_current_row(self):
        stats = import_prices_from_payload(self.session, self._payload())
        self.assertEqual(stats["inserted"], 1)
        row = get_current_market_price(self.session, "ANPR-ENSE1", "SR")
        assert row is not None
        self.assertTrue(row.is_current)
        self.assertAlmostEqual(row.low_price, 0.5)

    def test_unchanged_price_is_no_op(self):
        import_prices_from_payload(self.session, self._payload())
        stats = import_prices_from_payload(self.session, self._payload())
        self.assertEqual(stats["unchanged"], 1)
        count = self.session.scalars(select(PrintingMarketPrice)).all()
        self.assertEqual(len(count), 1)

    def test_price_change_creates_history(self):
        import_prices_from_payload(self.session, self._payload(0.5))
        stats = import_prices_from_payload(self.session, self._payload(0.9))
        self.assertEqual(stats["updated"], 1)
        rows = self.session.scalars(
            select(PrintingMarketPrice).order_by(PrintingMarketPrice.id)
        ).all()
        self.assertEqual(len(rows), 2)
        self.assertFalse(rows[0].is_current)
        self.assertIsNotNone(rows[0].valid_to)
        self.assertTrue(rows[1].is_current)
        self.assertAlmostEqual(rows[1].low_price, 0.9)

    def test_load_all_current_market_prices(self):
        import_prices_from_payload(self.session, self._payload())
        loaded = load_all_current_market_prices(self.session)
        self.assertEqual(len(loaded), 1)
        self.assertIn(("ANPR-ENSE1", "SR"), loaded)

    def test_bulk_unchanged_second_import(self):
        rows = [
            {
                "set_code": f"SET-{i:04d}",
                "rarity_code": "C",
                "low_price": 0.1 + i * 0.01,
                "avg_price": 0.2 + i * 0.01,
                "trend_price": 0.3 + i * 0.01,
                "discovery_status": "matched",
            }
            for i in range(100)
        ]
        payload = build_export_payload(rows)
        first = import_prices_from_payload(self.session, payload)
        self.assertEqual(first["inserted"], 100)
        second = import_prices_from_payload(self.session, payload)
        self.assertEqual(second["unchanged"], 100)
        count = self.session.scalars(select(PrintingMarketPrice)).all()
        self.assertEqual(len(count), 100)

    def test_fingerprint_skip_on_unchanged_payload(self):
        payload = self._payload()
        fp_path = Path(tempfile.mkdtemp()) / "last_import_fingerprint.json"
        first = import_prices_from_payload(
            self.session,
            payload,
            fingerprint_path=fp_path,
            skip_if_unchanged=True,
        )
        self.assertEqual(first["inserted"], 1)
        self.assertTrue(fp_path.is_file())

        second = import_prices_from_payload(
            self.session,
            payload,
            fingerprint_path=fp_path,
            skip_if_unchanged=True,
        )
        self.assertEqual(second.get("skipped"), 1)
        self.assertEqual(second.get("unchanged", 0), 0)

    def test_fingerprint_changes_when_prices_change(self):
        fp_path = Path(tempfile.mkdtemp()) / "last_import_fingerprint.json"
        fp1 = compute_import_fingerprint(self._payload(0.5))
        fp2 = compute_import_fingerprint(self._payload(0.9))
        self.assertNotEqual(fp1, fp2)


if __name__ == "__main__":
    unittest.main()
