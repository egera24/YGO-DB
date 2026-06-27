"""Collection list service: joins, filters, pagination."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.models import (
    Base,
    Card,
    CollectionFolder,
    CollectionItem,
    CollectionItemFolder,
    Printing,
    User,
)
from ygo_app.services import NO_FOLDER, list_collection


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


def _add_item(session, *, user_id, set_code, rarity_code, quantity=1, folder_id=None, printing_id=None):
    item = CollectionItem(
        user_id=user_id,
        set_code=set_code,
        rarity_code=rarity_code,
        card_name="Blue-Eyes White Dragon",
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

        binder = CollectionFolder(user_id=self.user_id, name="Binder A", name_key="binder a")
        session.add(binder)
        session.flush()
        self.binder_id = binder.id

        _add_item(
            session,
            user_id=self.user_id,
            set_code="LOB-001",
            rarity_code="(UR)",
            quantity=2,
            folder_id=self.binder_id,
            printing_id=self.printing_id,
        )
        _add_item(
            session,
            user_id=self.user_id,
            set_code="LOB-001",
            rarity_code="(SR)",
            quantity=1,
            folder_id=None,
        )
        other_user = User(email="other@test.example", hashed_password="x")
        session.add(other_user)
        session.flush()
        _add_item(
            session,
            user_id=other_user.id,
            set_code="LOB-001",
            rarity_code="(UR)",
            quantity=99,
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
        self.assertEqual(len(ur["folders"]), 1)
        self.assertEqual(ur["folders"][0]["name"], "Binder A")

    def test_folder_filter(self):
        session = self.Session()
        items, total = list_collection(
            session, user_id=self.user_id, folder=str(self.binder_id)
        )
        session.close()

        self.assertEqual(total, 1)
        self.assertEqual(items[0]["folders"][0]["name"], "Binder A")
        self.assertEqual(items[0]["quantity"], 2)

    def test_no_folder_filter(self):
        session = self.Session()
        items, total = list_collection(
            session, user_id=self.user_id, folder=NO_FOLDER
        )
        session.close()

        self.assertEqual(total, 1)
        self.assertIsNone(items[0]["folders"][0]["folder_id"])

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

    def test_sort_by_trade_quantity(self):
        session = self.Session()
        items = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalars().all()
        by_rarity = {item.rarity_code: item for item in items}
        by_rarity["(UR)"].trade_quantity = 5
        by_rarity["(SR)"].trade_quantity = 1
        session.commit()

        sorted_items, total = list_collection(
            session, user_id=self.user_id, sort="trade_quantity", limit=10
        )
        session.close()

        self.assertEqual(total, 2)
        self.assertEqual(sorted_items[0]["trade_quantity"], 1)
        self.assertEqual(sorted_items[1]["trade_quantity"], 5)


if __name__ == "__main__":
    unittest.main()
