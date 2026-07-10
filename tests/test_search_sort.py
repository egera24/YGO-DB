"""Tests for search_cards sort options."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, Card, CollectionItem, Printing, TcgSet, User
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


class TestSearchSort(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="sort@test.example", hashed_password="x")
        session.add(user)
        session.flush()
        self.user_id = user.id

        session.add_all(
            [
                TcgSet(abbr="OLD", name="Old Set", release_date=date(2002, 3, 8)),
                TcgSet(abbr="NEW", name="New Set", release_date=date(2020, 1, 15)),
                TcgSet(abbr="MID", name="Mid Set", release_date=date(2010, 6, 1)),
            ]
        )
        session.add_all(
            [
                Card(id=1, passcode=100, name="Alpha Card"),
                Card(id=2, passcode=300, name="Zulu Card"),
                Card(id=3, passcode=None, name="Beta Card"),
            ]
        )
        session.add_all(
            [
                Printing(
                    card_id=1,
                    set_code="OLD-EN001",
                    set_rarity_code="(C)",
                ),
                Printing(
                    card_id=1,
                    set_code="NEW-EN001",
                    set_rarity_code="(C)",
                ),
                Printing(
                    card_id=2,
                    set_code="MID-EN001",
                    set_rarity_code="(R)",
                ),
                Printing(
                    card_id=3,
                    set_code="OLD-EN002",
                    set_rarity_code="(C)",
                ),
            ]
        )
        session.add_all(
            [
                CollectionItem(
                    user_id=self.user_id,
                    set_code="OLD-EN001",
                    rarity_code="(C)",
                    quantity=2,
                ),
                CollectionItem(
                    user_id=self.user_id,
                    set_code="NEW-EN001",
                    rarity_code="(C)",
                    quantity=5,
                ),
                CollectionItem(
                    user_id=self.user_id,
                    set_code="MID-EN001",
                    rarity_code="(R)",
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
            if "user_id" not in kwargs:
                kwargs["user_id"] = self.user_id
            cards, _total = search_cards(session, limit=100, **kwargs)
            return [c.id for c in cards]
        finally:
            session.close()

    def test_sort_name_asc(self):
        self.assertEqual(self._ids(sort="name", sort_dir="asc"), [1, 3, 2])

    def test_sort_name_desc(self):
        self.assertEqual(self._ids(sort="name", sort_dir="desc"), [2, 3, 1])

    def test_sort_passcode_asc(self):
        self.assertEqual(self._ids(sort="passcode", sort_dir="asc"), [1, 2, 3])

    def test_sort_passcode_desc(self):
        self.assertEqual(self._ids(sort="passcode", sort_dir="desc"), [3, 2, 1])

    def test_sort_release_date_asc(self):
        self.assertEqual(self._ids(sort="release_date", sort_dir="asc"), [3, 2, 1])

    def test_sort_release_date_desc(self):
        self.assertEqual(self._ids(sort="release_date", sort_dir="desc"), [1, 2, 3])

    def test_sort_release_date_desc_nulls_last(self):
        session = self.Session()
        try:
            session.add(
                Card(
                    id=4,
                    passcode=4,
                    name="Undated Only",
                )
            )
            session.add(
                Printing(
                    card_id=4,
                    set_code="TKN5-EN099",
                    set_rarity_code="(T)",
                )
            )
            session.add(TcgSet(abbr="TKN5", name="Token Pack", release_date=None))
            session.commit()
            cards, _total = search_cards(
                session, limit=100, user_id=self.user_id, sort="release_date", sort_dir="desc"
            )
            ids = [c.id for c in cards]
            self.assertEqual(ids[0], 1)
            self.assertIn(4, ids)
            self.assertGreater(ids.index(4), ids.index(1))
        finally:
            session.close()

    def test_sort_owned_quantity_asc(self):
        self.assertEqual(self._ids(sort="owned_quantity", sort_dir="asc"), [3, 2, 1])

    def test_sort_owned_quantity_desc(self):
        self.assertEqual(self._ids(sort="owned_quantity", sort_dir="desc"), [1, 2, 3])

    def test_sort_owned_quantity_without_user(self):
        self.assertEqual(
            self._ids(sort="owned_quantity", sort_dir="desc", user_id=None),
            [3, 2, 1],
        )


if __name__ == "__main__":
    unittest.main()
