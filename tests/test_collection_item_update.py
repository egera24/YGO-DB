"""Editing collection items: set/rarity reassignment + condition validation."""

from __future__ import annotations

import tempfile
import unittest

from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, Card, CollectionItem, Printing, User
from ygo_app.schemas import CollectionItemUpdate
from ygo_app.services import update_collection_item


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


class TestCollectionItemUpdate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="edit@test.example", hashed_password="x")
        session.add(user)
        session.flush()
        self.user_id = user.id

        card = Card(id=85087012, name="Card Trooper")
        session.add(card)
        session.flush()

        self.printing_a = Printing(
            card_id=card.id,
            set_code="LOB-001",
            set_name="Legend of Blue Eyes",
            set_rarity="Ultra Rare",
            set_rarity_code="(UR)",
        )
        self.printing_b = Printing(
            card_id=card.id,
            set_code="RA03-EN172",
            set_name="Quarter Century Bonanza",
            set_rarity="Secret Rare",
            set_rarity_code="(ScR)",
        )
        session.add_all([self.printing_a, self.printing_b])
        session.flush()

        item = CollectionItem(
            user_id=self.user_id,
            set_code="LOB-001",
            rarity_code="(UR)",
            card_name="Card Trooper",
            quantity=2,
            printing_id=self.printing_a.id,
        )
        session.add(item)
        session.commit()
        self.item_id = item.id
        self.printing_b_id = self.printing_b.id
        session.close()

    def tearDown(self):
        self.engine.dispose()

    def test_reassign_set_and_rarity_relinks_printing(self):
        session = self.Session()
        item = session.get(CollectionItem, self.item_id)
        update_collection_item(
            session,
            user_id=self.user_id,
            item=item,
            data={"set_code": "RA03-EN172", "rarity": "(ScR)"},
        )
        session.refresh(item)
        self.assertEqual(item.set_code, "RA03-EN172")
        self.assertEqual(item.rarity_code, "(ScR)")
        self.assertEqual(item.printing_id, self.printing_b_id)
        self.assertEqual(item.set_name, "Quarter Century Bonanza")
        self.assertEqual(item.expansion_code, "RA03")
        self.assertEqual(item.card_name, "Card Trooper")
        session.close()

    def test_rarity_without_parens_is_normalized(self):
        session = self.Session()
        item = session.get(CollectionItem, self.item_id)
        update_collection_item(
            session,
            user_id=self.user_id,
            item=item,
            data={"set_code": "RA03-EN172", "rarity": "ScR"},
        )
        session.refresh(item)
        self.assertEqual(item.rarity_code, "(ScR)")
        session.close()

    def test_unknown_printing_rejected(self):
        session = self.Session()
        item = session.get(CollectionItem, self.item_id)
        with self.assertRaises(ValueError):
            update_collection_item(
                session,
                user_id=self.user_id,
                item=item,
                data={"set_code": "FAKE-EN999", "rarity": "(UR)"},
            )
        session.close()

    def test_duplicate_user_row_rejected(self):
        session = self.Session()
        session.add(
            CollectionItem(
                user_id=self.user_id,
                set_code="RA03-EN172",
                rarity_code="(ScR)",
                quantity=1,
                printing_id=self.printing_b_id,
            )
        )
        session.commit()
        item = session.get(CollectionItem, self.item_id)
        with self.assertRaises(ValueError):
            update_collection_item(
                session,
                user_id=self.user_id,
                item=item,
                data={"set_code": "RA03-EN172", "rarity": "(ScR)"},
            )
        session.close()

    def test_same_set_and_rarity_is_noop(self):
        session = self.Session()
        item = session.get(CollectionItem, self.item_id)
        original_printing_id = item.printing_id
        update_collection_item(
            session,
            user_id=self.user_id,
            item=item,
            data={"set_code": "LOB-001", "rarity": "(UR)", "quantity": 5},
        )
        session.refresh(item)
        self.assertEqual(item.printing_id, original_printing_id)
        self.assertEqual(item.quantity, 5)
        session.close()

    def test_condition_schema_accepts_canonical_values(self):
        for value in (
            "Mint",
            "NearMint",
            "Excellent",
            "Good",
            "LightPlayed",
            "Played",
            "Poor",
        ):
            body = CollectionItemUpdate(condition=value)
            self.assertEqual(body.condition, value)

    def test_condition_schema_rejects_unknown_values(self):
        with self.assertRaises(ValidationError):
            CollectionItemUpdate(condition="Damaged")

    def test_trade_quantity_independent_of_quantity(self):
        session = self.Session()
        item = session.get(CollectionItem, self.item_id)
        update_collection_item(
            session,
            user_id=self.user_id,
            item=item,
            data={"trade_quantity": 10, "quantity": 2},
        )
        session.refresh(item)
        self.assertEqual(item.trade_quantity, 10)
        self.assertEqual(item.quantity, 2)
        session.close()

    def test_patch_sell_price(self):
        session = self.Session()
        item = session.get(CollectionItem, self.item_id)
        update_collection_item(
            session,
            user_id=self.user_id,
            item=item,
            data={"sell_price": 4.5},
        )
        session.refresh(item)
        self.assertEqual(item.sell_price, 4.5)
        session.close()


if __name__ == "__main__":
    unittest.main()
