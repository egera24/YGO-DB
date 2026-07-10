"""Tests for collection list sort options."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, Card, CollectionItem, Printing, TcgSet, User
from ygo_app.services import list_collection


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


class TestCollectionSort(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="coll-sort@test.example", hashed_password="x")
        session.add(user)
        session.flush()
        self.user_id = user.id

        session.add_all(
            [
                TcgSet(abbr="OLD", name="Old Set", release_date=date(2002, 3, 8)),
                TcgSet(abbr="NEW", name="New Set", release_date=date(2020, 1, 15)),
            ]
        )
        session.add_all(
            [
                Card(id=10, passcode=111, name="Alpha"),
                Card(id=20, passcode=999, name="Omega"),
            ]
        )
        session.add_all(
            [
                Printing(
                    card_id=10,
                    set_code="OLD-EN001",
                    set_rarity_code="(C)",
                ),
                Printing(
                    card_id=20,
                    set_code="NEW-EN001",
                    set_rarity_code="(R)",
                ),
            ]
        )
        session.add_all(
            [
                CollectionItem(
                    id=1,
                    user_id=self.user_id,
                    set_code="OLD-EN001",
                    rarity_code="(C)",
                    card_name="Alpha",
                    quantity=3,
                ),
                CollectionItem(
                    id=2,
                    user_id=self.user_id,
                    set_code="NEW-EN001",
                    rarity_code="(R)",
                    card_name="Omega",
                    quantity=1,
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
            items, _total = list_collection(session, user_id=self.user_id, limit=100, **kwargs)
            return [item["id"] for item in items]
        finally:
            session.close()

    def test_sort_set_code_asc(self):
        self.assertEqual(self._ids(sort="set_code", sort_dir="asc"), [2, 1])

    def test_sort_set_code_desc(self):
        self.assertEqual(self._ids(sort="set_code", sort_dir="desc"), [1, 2])

    def test_sort_quantity_desc(self):
        self.assertEqual(self._ids(sort="quantity", sort_dir="desc"), [1, 2])

    def test_sort_passcode_asc(self):
        self.assertEqual(self._ids(sort="passcode", sort_dir="asc"), [1, 2])

    def test_sort_passcode_desc(self):
        self.assertEqual(self._ids(sort="passcode", sort_dir="desc"), [2, 1])

    def test_sort_release_date_asc(self):
        self.assertEqual(self._ids(sort="release_date", sort_dir="asc"), [1, 2])

    def test_sort_release_date_desc(self):
        self.assertEqual(self._ids(sort="release_date", sort_dir="desc"), [2, 1])


if __name__ == "__main__":
    unittest.main()
