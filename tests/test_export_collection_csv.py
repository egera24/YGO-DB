"""Collection CSV export and DragonShield round-trip."""

from __future__ import annotations

import csv
import io
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.collection_export import (
    export_collection_csv,
    list_export_formats,
)
from ygo_app.import_data import import_collection_csv
from ygo_app.models import (
    Base,
    Card,
    CollectionFolder,
    CollectionItem,
    CollectionItemFolder,
    Printing,
    PrintingMarketPrice,
    User,
)
from ygo_app.services import NO_FOLDER


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

        folder = CollectionFolder(user_id=self.user_id, name="main", name_key="main")
        session.add(folder)
        session.flush()
        item = CollectionItem(
            user_id=self.user_id,
            set_code="LOB-001",
            rarity_code="(UR)",
            card_name="Ahrima, the Wicked Warden",
            expansion_code="LOB",
            set_name="Legend of Blue Eyes White Dragon",
            quantity=2,
            trade_quantity=1,
            condition="NearMint",
            edition="Foil",
            language="English",
            price_bought=0.52,
            date_bought="2019-09-19",
            sell_price=0.45,
            printing_id=self.printing_id,
        )
        session.add(item)
        session.flush()
        session.add(
            CollectionItemFolder(
                collection_item_id=item.id,
                folder_id=folder.id,
                quantity=2,
            )
        )
        session.add(
            PrintingMarketPrice(
                set_code="LOB-001",
                rarity_code="(UR)",
                low_price=0.05,
                avg_price=0.26,
                trend_price=0.32,
                valid_from=datetime.utcnow(),
                is_current=True,
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

    def test_dragonshield_export_uses_cardmarket_prices(self):
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
        self.assertEqual(row["AVG"], "0.26")
        self.assertEqual(row["LOW"], "0.05")
        self.assertEqual(row["TREND"], "0.32")
        self.assertEqual(row["Sell Price"], "0.45")

    def test_export_zero_fills_missing_market_prices(self):
        session = self.Session()
        session.query(PrintingMarketPrice).delete()
        item = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalar_one()
        item.sell_price = None
        session.commit()
        csv_text, _, _ = export_collection_csv(
            session, user_id=self.user_id, format_id="dragonshield"
        )
        session.close()

        reader = csv.DictReader(io.StringIO("\n".join(csv_text.splitlines()[1:])))
        row = next(reader)
        self.assertEqual(row["AVG"], "0")
        self.assertEqual(row["LOW"], "0")
        self.assertEqual(row["TREND"], "0")
        self.assertEqual(row["Sell Price"], "0")

    def test_export_sell_price_falls_back_to_market_trend(self):
        session = self.Session()
        item = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalar_one()
        item.sell_price = None
        session.commit()
        csv_text, _, _ = export_collection_csv(
            session, user_id=self.user_id, format_id="dragonshield"
        )
        session.close()

        reader = csv.DictReader(io.StringIO("\n".join(csv_text.splitlines()[1:])))
        row = next(reader)
        self.assertEqual(row["Sell Price"], "0.32")

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
            folder = session.execute(
                select(CollectionFolder).where(CollectionFolder.user_id == self.user_id)
            ).scalar_one()
            allocation = session.execute(
                select(CollectionItemFolder).where(
                    CollectionItemFolder.collection_item_id == item.id
                )
            ).scalar_one()
            session.close()
            self.assertEqual(item.set_code, "LOB-001")
            self.assertEqual(item.rarity_code, "(UR)")
            self.assertEqual(item.quantity, 2)
            self.assertEqual(item.trade_quantity, 1)
            self.assertAlmostEqual(item.price_bought, 0.52)
            self.assertIsNone(item.sell_price)
            self.assertEqual(item.edition, "Foil")
            self.assertEqual(folder.name, "main")
            self.assertEqual(allocation.folder_id, folder.id)
            self.assertEqual(allocation.quantity, 2)
        finally:
            self.init_db_patcher.stop()
            self.session_factory_patcher.stop()


def _read_export_rows(csv_text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO("\n".join(csv_text.splitlines()[1:])))
    return list(reader)


class TestExportCollectionCsvFolderFilter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="export-folders@test.example", hashed_password="x")
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

        main = CollectionFolder(user_id=self.user_id, name="main", name_key="main")
        trade = CollectionFolder(user_id=self.user_id, name="trade", name_key="trade")
        session.add_all([main, trade])
        session.flush()
        self.main_folder_id = main.id
        self.trade_folder_id = trade.id

        split_item = CollectionItem(
            user_id=self.user_id,
            set_code="LOB-001",
            rarity_code="(UR)",
            card_name="Split Card",
            expansion_code="LOB",
            quantity=2,
            printing_id=printing.id,
        )
        session.add(split_item)
        session.flush()
        session.add_all(
            [
                CollectionItemFolder(
                    collection_item_id=split_item.id,
                    folder_id=main.id,
                    quantity=1,
                ),
                CollectionItemFolder(
                    collection_item_id=split_item.id,
                    folder_id=trade.id,
                    quantity=1,
                ),
            ]
        )

        loose_item = CollectionItem(
            user_id=self.user_id,
            set_code="LOB-002",
            rarity_code="(UR)",
            card_name="Loose Card",
            expansion_code="LOB",
            quantity=3,
            printing_id=printing.id,
        )
        session.add(loose_item)
        session.flush()
        session.add(
            CollectionItemFolder(
                collection_item_id=loose_item.id,
                folder_id=None,
                quantity=3,
            )
        )
        session.commit()
        session.close()

    def tearDown(self):
        self.engine.dispose()

    def test_export_filters_single_folder(self):
        session = self.Session()
        csv_text, _, _ = export_collection_csv(
            session,
            user_id=self.user_id,
            format_id="dragonshield",
            folder_ids=[str(self.main_folder_id)],
        )
        session.close()

        rows = _read_export_rows(csv_text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Folder Name"], "main")
        self.assertEqual(rows[0]["Quantity"], "1")
        self.assertEqual(rows[0]["Card Name"], "Split Card")

    def test_export_filters_multiple_folders(self):
        session = self.Session()
        csv_text, _, _ = export_collection_csv(
            session,
            user_id=self.user_id,
            format_id="dragonshield",
            folder_ids=[str(self.main_folder_id), str(self.trade_folder_id)],
        )
        session.close()

        rows = _read_export_rows(csv_text)
        self.assertEqual(len(rows), 2)
        folders = {row["Folder Name"] for row in rows}
        self.assertEqual(folders, {"main", "trade"})
        self.assertTrue(all(row["Quantity"] == "1" for row in rows))
        self.assertTrue(all(row["Card Name"] == "Split Card" for row in rows))

    def test_export_filters_no_folder_only(self):
        session = self.Session()
        csv_text, _, _ = export_collection_csv(
            session,
            user_id=self.user_id,
            format_id="dragonshield",
            folder_ids=[NO_FOLDER],
        )
        session.close()

        rows = _read_export_rows(csv_text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Folder Name"], "")
        self.assertEqual(rows[0]["Quantity"], "3")
        self.assertEqual(rows[0]["Card Name"], "Loose Card")

    def test_export_unknown_folder_raises(self):
        session = self.Session()
        with self.assertRaises(ValueError):
            export_collection_csv(
                session,
                user_id=self.user_id,
                format_id="dragonshield",
                folder_ids=["99999"],
            )
        session.close()

    def test_export_empty_folder_list_raises(self):
        session = self.Session()
        with self.assertRaises(ValueError):
            export_collection_csv(
                session,
                user_id=self.user_id,
                format_id="dragonshield",
                folder_ids=[],
            )
        session.close()


if __name__ == "__main__":
    unittest.main()
