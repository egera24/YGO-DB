"""Sell price defaults and updates for collection items."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, Card, Printing, PrintingMarketPrice, User
from ygo_app.services import add_collection_item, update_collection_item


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


class TestCollectionSellPrice(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="sell@test.example", hashed_password="x")
        session.add(user)
        session.flush()
        self.user_id = user.id

        card = Card(id=89631139, name="Blue-Eyes White Dragon")
        session.add(card)
        printing = Printing(
            card_id=card.id,
            set_code="LOB-001",
            set_name="Legend of Blue Eyes White Dragon",
            set_rarity_code="(UR)",
            set_rarity="Ultra Rare",
        )
        session.add(printing)
        session.flush()
        self.printing_id = printing.id

        session.add(
            PrintingMarketPrice(
                set_code="LOB-001",
                rarity_code="(UR)",
                trend_price=12.5,
            )
        )
        session.commit()
        session.close()

    def tearDown(self):
        self.engine.dispose()

    def test_add_without_override_leaves_sell_price_null(self):
        session = self.Session()
        item = add_collection_item(
            session,
            self.user_id,
            {"set_code": "LOB-001", "rarity": "(UR)", "quantity": 1},
        )
        self.assertIsNone(item.sell_price)
        session.close()

    def test_add_enriches_metadata_from_catalog(self):
        session = self.Session()
        item = add_collection_item(
            session,
            self.user_id,
            {"set_code": "LOB-001", "rarity": "(UR)", "quantity": 1},
        )
        self.assertEqual(item.card_name, "Blue-Eyes White Dragon")
        self.assertEqual(item.expansion_code, "LOB")
        self.assertEqual(item.set_name, "Legend of Blue Eyes White Dragon")
        session.close()

    def test_add_without_market_data_leaves_sell_price_null(self):
        session = self.Session()
        item = add_collection_item(
            session,
            self.user_id,
            {"set_code": "LOB-001", "rarity": "(SR)", "quantity": 1},
        )
        self.assertIsNone(item.sell_price)
        session.close()

    def test_add_honors_explicit_sell_price(self):
        session = self.Session()
        item = add_collection_item(
            session,
            self.user_id,
            {
                "set_code": "LOB-001",
                "rarity": "(UR)",
                "quantity": 1,
                "sell_price": 9.99,
            },
        )
        self.assertEqual(item.sell_price, 9.99)
        session.close()

    def test_patch_sell_price(self):
        session = self.Session()
        item = add_collection_item(
            session,
            self.user_id,
            {"set_code": "LOB-001", "rarity": "(UR)", "quantity": 1},
        )
        update_collection_item(
            session,
            user_id=self.user_id,
            item=item,
            data={"sell_price": 7.25},
        )
        session.refresh(item)
        self.assertEqual(item.sell_price, 7.25)
        session.close()


if __name__ == "__main__":
    unittest.main()
