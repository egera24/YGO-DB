"""Tests for search_cards for_trade_only filter."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, Card, CollectionItem, Printing, User
from ygo_app.schemas import normalize_search_preset_params
from ygo_app.services import search_cards


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


class TestSearchForTradeFilter(unittest.TestCase):
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

        session.add_all(
            [
                Card(id=1, passcode=100, name="Trade Card"),
                Card(id=2, passcode=200, name="Owned Only"),
                Card(id=3, passcode=300, name="Not Owned"),
            ]
        )
        session.add_all(
            [
                Printing(card_id=1, set_code="SET-001", set_rarity_code="(C)"),
                Printing(card_id=2, set_code="SET-002", set_rarity_code="(C)"),
                Printing(card_id=3, set_code="SET-003", set_rarity_code="(C)"),
            ]
        )
        session.add_all(
            [
                CollectionItem(
                    user_id=self.user_id,
                    set_code="SET-001",
                    rarity_code="(C)",
                    quantity=1,
                    trade_quantity=2,
                ),
                CollectionItem(
                    user_id=self.user_id,
                    set_code="SET-002",
                    rarity_code="(C)",
                    quantity=1,
                    trade_quantity=0,
                ),
            ]
        )
        session.commit()
        session.close()

    def tearDown(self):
        self.engine.dispose()

    def _ids(self, **kwargs) -> list[int]:
        session = self.Session()
        try:
            if "user_id" not in kwargs:
                kwargs["user_id"] = self.user_id
            cards, _total = search_cards(session, limit=100, **kwargs)
            return [c.id for c in cards]
        finally:
            session.close()

    def test_for_trade_only_includes_trade_cards(self):
        self.assertEqual(self._ids(for_trade_only=True), [1])

    def test_for_trade_only_excludes_owned_without_trade_qty(self):
        self.assertNotIn(2, self._ids(for_trade_only=True))

    def test_for_trade_only_excludes_unowned_cards(self):
        self.assertNotIn(3, self._ids(for_trade_only=True))

    def test_for_trade_only_without_user_returns_empty(self):
        self.assertEqual(self._ids(for_trade_only=True, user_id=None), [])

    def test_for_trade_only_combined_with_owned_only(self):
        self.assertEqual(
            self._ids(for_trade_only=True, owned_only=True),
            [1],
        )

    def test_preset_param_key_accepted(self):
        cleaned = normalize_search_preset_params({"for_trade_only": "true"})
        self.assertEqual(cleaned, {"for_trade_only": "true"})


if __name__ == "__main__":
    unittest.main()
