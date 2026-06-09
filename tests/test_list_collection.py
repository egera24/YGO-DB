"""Collection list service: joins, filters, pagination."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, Card, CollectionItem, Printing, User
from ygo_app.services import UNASSIGNED_FOLDER, list_collection


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


class TestListCollection(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="list@test.example", hashed_password="x")
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

        session.add(
            CollectionItem(
                user_id=self.user_id,
                set_code="LOB-001",
                rarity_code="(UR)",
                card_name="Blue-Eyes White Dragon",
                quantity=2,
                folder_name="Binder A",
                printing_id=self.printing_id,
            )
        )
        session.add(
            CollectionItem(
                user_id=self.user_id,
                set_code="LOB-001",
                rarity_code="(SR)",
                card_name="Blue-Eyes White Dragon",
                quantity=1,
                folder_name=None,
            )
        )
        other_user = User(email="other@test.example", hashed_password="x")
        session.add(other_user)
        session.flush()
        session.add(
            CollectionItem(
                user_id=other_user.id,
                set_code="LOB-001",
                rarity_code="(UR)",
                quantity=99,
            )
        )
        session.commit()
        session.close()

    def tearDown(self):
        self.engine.dispose()

    def test_list_returns_card_id_and_image_via_join(self):
        session = self.Session()
        items, total = list_collection(session, user_id=self.user_id, limit=10)
        session.close()

        self.assertEqual(total, 2)
        ur = next(i for i in items if i["rarity_code"] == "(UR)")
        self.assertEqual(ur["card_id"], 89631139)
        self.assertEqual(ur["image_url_small"], "https://example.com/bewd-small.png")
        self.assertEqual(ur["rarity_display"], "UR")

    def test_folder_filter(self):
        session = self.Session()
        items, total = list_collection(
            session, user_id=self.user_id, folder="Binder A"
        )
        session.close()

        self.assertEqual(total, 1)
        self.assertEqual(items[0]["folder_name"], "Binder A")

    def test_unassigned_folder_filter(self):
        session = self.Session()
        items, total = list_collection(
            session, user_id=self.user_id, folder=UNASSIGNED_FOLDER
        )
        session.close()

        self.assertEqual(total, 1)
        self.assertIsNone(items[0]["folder_name"])

    def test_pagination(self):
        session = self.Session()
        page1, total = list_collection(session, user_id=self.user_id, limit=1, offset=0)
        page2, _ = list_collection(session, user_id=self.user_id, limit=1, offset=1)
        session.close()

        self.assertEqual(total, 2)
        self.assertEqual(len(page1), 1)
        self.assertEqual(len(page2), 1)
        self.assertNotEqual(page1[0]["id"], page2[0]["id"])

    def test_query_count_bounded(self):
        session = self.Session()
        query_count = 0

        @event.listens_for(self.engine, "before_cursor_execute")
        def _count_queries(conn, cursor, statement, parameters, context, executemany):
            nonlocal query_count
            query_count += 1

        try:
            list_collection(session, user_id=self.user_id, limit=10)
        finally:
            event.remove(self.engine, "before_cursor_execute", _count_queries)
        session.close()

        self.assertLessEqual(query_count, 4)


if __name__ == "__main__":
    unittest.main()
