"""Collection detail stats: folder scope, price sums, max value card."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

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
from ygo_app.services import NO_FOLDER, collection_detail_stats


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


def _add_item(
    session,
    *,
    user_id,
    set_code,
    rarity_code,
    card_name,
    quantity=1,
    folder_id=None,
    printing_id=None,
):
    item = CollectionItem(
        user_id=user_id,
        set_code=set_code,
        rarity_code=rarity_code,
        card_name=card_name,
        quantity=quantity,
        printing_id=printing_id,
    )
    session.add(item)
    session.flush()
    session.add(
        CollectionItemFolder(
            collection_item_id=item.id,
            folder_id=folder_id,
            quantity=quantity,
        )
    )
    return item


class TestCollectionDetailStats(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="stats@test.example", hashed_password="x")
        session.add(user)
        session.flush()
        self.user_id = user.id

        card = Card(
            id=89631139,
            name="Blue-Eyes White Dragon",
            image_url_small="https://example.com/bewd-small.png",
        )
        session.add(card)
        printing = Printing(
            card_id=89631139,
            set_code="LOB-001",
            set_rarity_code="(UR)",
            set_rarity="Ultra Rare",
        )
        session.add(printing)
        session.flush()
        self.printing_id = printing.id

        binder = CollectionFolder(user_id=self.user_id, name="Binder A", name_key="binder a")
        session.add(binder)
        session.flush()
        self.binder_id = binder.id

        now = datetime.now(timezone.utc)
        session.add(
            PrintingMarketPrice(
                set_code="LOB-001",
                rarity_code="(UR)",
                low_price=1.0,
                avg_price=2.0,
                trend_price=10.0,
                valid_from=now,
                is_current=True,
            )
        )
        session.add(
            PrintingMarketPrice(
                set_code="LOB-002",
                rarity_code="(SR)",
                low_price=0.5,
                avg_price=1.0,
                trend_price=5.0,
                valid_from=now,
                is_current=True,
            )
        )

        _add_item(
            session,
            user_id=self.user_id,
            set_code="LOB-001",
            rarity_code="(UR)",
            card_name="Blue-Eyes White Dragon",
            quantity=2,
            folder_id=self.binder_id,
            printing_id=self.printing_id,
        )
        _add_item(
            session,
            user_id=self.user_id,
            set_code="LOB-002",
            rarity_code="(SR)",
            card_name="Dark Magician",
            quantity=3,
            folder_id=None,
        )
        session.commit()
        session.close()

    def tearDown(self):
        self.engine.dispose()

    def test_all_folder_qty_weighted_sums_and_max(self):
        session = self.Session()
        stats = collection_detail_stats(session, user_id=self.user_id)
        session.close()

        self.assertEqual(stats["folder_label"], "All")
        self.assertEqual(stats["unique_printings"], 2)
        self.assertEqual(stats["total_quantity"], 5)
        self.assertAlmostEqual(stats["sum_low_price"], 1.0 * 2 + 0.5 * 3)
        self.assertAlmostEqual(stats["sum_avg_price"], 2.0 * 2 + 1.0 * 3)
        self.assertAlmostEqual(stats["sum_trend_price"], 10.0 * 2 + 5.0 * 3)
        self.assertEqual(stats["max_value_item"]["card_name"], "Blue-Eyes White Dragon")
        self.assertEqual(stats["max_value_item"]["trend_price"], 10.0)

    def test_folder_scope(self):
        session = self.Session()
        stats = collection_detail_stats(
            session, user_id=self.user_id, folder=str(self.binder_id)
        )
        session.close()

        self.assertEqual(stats["folder_label"], "Binder A")
        self.assertEqual(stats["unique_printings"], 1)
        self.assertEqual(stats["total_quantity"], 2)
        self.assertAlmostEqual(stats["sum_trend_price"], 20.0)
        self.assertEqual(stats["max_value_item"]["set_code"], "LOB-001")

    def test_no_folder_scope(self):
        session = self.Session()
        stats = collection_detail_stats(
            session, user_id=self.user_id, folder=NO_FOLDER
        )
        session.close()

        self.assertEqual(stats["folder_label"], "No Folder")
        self.assertEqual(stats["unique_printings"], 1)
        self.assertEqual(stats["total_quantity"], 3)
        self.assertEqual(stats["max_value_item"]["card_name"], "Dark Magician")


if __name__ == "__main__":
    unittest.main()
