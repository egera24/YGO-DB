"""Owned and trade quantity aggregation on card summaries."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, Card, CollectionItem, Printing, User
from ygo_app.services import card_summaries_batch


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


class TestCardSummaryTradeQuantity(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="trade@test.example", hashed_password="x")
        session.add(user)
        session.flush()
        self.user_id = user.id

        card = Card(id=89631139, name="Blue-Eyes White Dragon")
        session.add(card)
        session.add_all(
            [
                Printing(
                    card_id=card.id,
                    set_code="LOB-001",
                    set_rarity_code="(UR)",
                ),
                Printing(
                    card_id=card.id,
                    set_code="LOB-002",
                    set_rarity_code="(SR)",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                CollectionItem(
                    user_id=self.user_id,
                    set_code="LOB-001",
                    rarity_code="(UR)",
                    quantity=2,
                    trade_quantity=1,
                ),
                CollectionItem(
                    user_id=self.user_id,
                    set_code="LOB-002",
                    rarity_code="(SR)",
                    quantity=3,
                    trade_quantity=2,
                ),
            ]
        )
        session.commit()
        self.card_id = card.id
        session.close()

    def tearDown(self):
        self.engine.dispose()

    def test_card_summaries_batch_sums_trade_quantity(self):
        session = self.Session()
        card = session.get(Card, self.card_id)
        extras = card_summaries_batch(session, [card], self.user_id)
        session.close()

        summary = extras[self.card_id]
        self.assertTrue(summary["owned"])
        self.assertEqual(summary["owned_quantity"], 5)
        self.assertEqual(summary["trade_quantity"], 3)


if __name__ == "__main__":
    unittest.main()
