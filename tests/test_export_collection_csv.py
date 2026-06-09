"""Collection CSV export and DragonShield round-trip."""

from __future__ import annotations

import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.collection_export import (
    export_collection_csv,
    list_export_formats,
)
from ygo_app.import_data import import_collection_csv
from ygo_app.models import Base, Card, CollectionItem, Printing, User


def _sqlite_engine(path: str):
    eng = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return eng


class TestExportCollectionCsv(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="export@test.example", hashed_password="x")
        session.add(user)
        session.flush()
        self.user_id = user.id

        card = Card(id=89631139, name="Blue-Eyes White Dragon")
        session.add(card)
        printing = Printing(
            card_id=89631139,
            set_code="LOB-001",
            set_name="Legend of Blue Eyes White Dragon",
            set_rarity_code="(UR)",
            set_rarity="Ultra Rare",
        )
        session.add(printing)
        session.flush()
        self.printing_id = printing.id

        session.add(
            CollectionItem(
                user_id=self.user_id,
                set_code="LOB-001",
                rarity_code="(UR)",
                card_name='Ahrima, the Wicked Warden',
                expansion_code="LOB",
                set_name="Legend of Blue Eyes White Dragon",
                quantity=2,
                trade_quantity=1,
                condition="NearMint",
                edition="Foil",
                language="English",
                folder_name="main",
                price_bought=0.52,
                date_bought="2019-09-19",
                avg_price=0.26,
                low_price=0.05,
                trend_price=0.32,
                printing_id=self.printing_id,
            )
        )
        session.commit()
        session.close()

    def tearDown(self):
        self.engine.dispose()

    def test_list_export_formats_includes_dragonshield(self):
        formats = list_export_formats()
        self.assertTrue(any(f["id"] == "dragonshield" for f in formats))
        dragon = next(f for f in formats if f["id"] == "dragonshield")
        for key in ("id", "label", "filename", "description"):
            self.assertIn(key, dragon)

    def test_dragonshield_export_fields(self):
        session = self.Session()
        csv_text, media_type, filename = export_collection_csv(
            session, user_id=self.user_id, format_id="dragonshield"
        )
        session.close()

        self.assertEqual(media_type, "text/csv; charset=utf-8")
        self.assertEqual(filename, "ygo_collection_dragonshield.csv")
        lines = csv_text.splitlines()
        self.assertEqual(lines[0], '"sep=,"')

        reader = csv.DictReader(io.StringIO("\n".join(lines[1:])))
        rows = list(reader)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["Card Number"], "LOB-001")
        self.assertEqual(row["Rarity"], "UR")
        self.assertEqual(row["Card Name"], "Ahrima, the Wicked Warden")
        self.assertEqual(row["Set Code"], "LOB")
        self.assertEqual(row["Quantity"], "2")
        self.assertEqual(row["Trade Quantity"], "1")
        self.assertEqual(row["Printing"], "Foil")
        self.assertEqual(row["Condition"], "NearMint")
        self.assertEqual(row["TREND"], "0.32")

    def test_unknown_format_raises(self):
        session = self.Session()
        with self.assertRaises(ValueError):
            export_collection_csv(session, user_id=self.user_id, format_id="unknown")
        session.close()

    def test_empty_collection_headers_only(self):
        session = self.Session()
        session.query(CollectionItem).delete()
        session.commit()
        csv_text, _, _ = export_collection_csv(
            session, user_id=self.user_id, format_id="dragonshield"
        )
        session.close()

        lines = csv_text.splitlines()
        self.assertEqual(lines[0], '"sep=,"')
        reader = csv.DictReader(io.StringIO("\n".join(lines[1:])))
        self.assertEqual(list(reader), [])

    def test_round_trip_export_then_import(self):
        session = self.Session()
        csv_text, _, _ = export_collection_csv(
            session, user_id=self.user_id, format_id="dragonshield"
        )
        session.close()

        csv_path = Path(self._tmp.name).with_suffix(".export.csv")
        csv_path.write_text(csv_text, encoding="utf-8")

        self.session_factory_patcher = patch(
            "ygo_app.import_data.SessionLocal", self.Session
        )
        self.init_db_patcher = patch("ygo_app.import_data.init_db", lambda: None)
        self.session_factory_patcher.start()
        self.init_db_patcher.start()
        try:
            result = import_collection_csv(
                csv_path, user_id=self.user_id, replace=True
            )
            self.assertEqual(result.imported, 1)
            self.assertEqual(result.rejected, [])

            session = self.Session()
            item = session.execute(
                select(CollectionItem).where(CollectionItem.user_id == self.user_id)
            ).scalar_one()
            session.close()
            self.assertEqual(item.set_code, "LOB-001")
            self.assertEqual(item.rarity_code, "(UR)")
            self.assertEqual(item.quantity, 2)
            self.assertEqual(item.trade_quantity, 1)
            self.assertEqual(item.edition, "Foil")
            self.assertEqual(item.folder_name, "main")
        finally:
            self.init_db_patcher.stop()
            self.session_factory_patcher.stop()


if __name__ == "__main__":
    unittest.main()
