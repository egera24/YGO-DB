"""Collection stats aggregates."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, CollectionFolder, CollectionItem, CollectionItemFolder, User
from ygo_app.services import collection_stats


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


def _add_item(session, *, user_id, set_code, rarity_code, quantity, folder_id):
    item = CollectionItem(
        user_id=user_id,
        set_code=set_code,
        rarity_code=rarity_code,
        quantity=quantity,
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


class TestCollectionStats(unittest.TestCase):
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

        box = CollectionFolder(user_id=self.user_id, name="Box 1", name_key="box 1")
        session.add(box)
        session.flush()

        _add_item(
            session,
            user_id=self.user_id,
            set_code="A-001",
            rarity_code="(C)",
            quantity=3,
            folder_id=box.id,
        )
        _add_item(
            session,
            user_id=self.user_id,
            set_code="B-002",
            rarity_code="(R)",
            quantity=2,
            folder_id=box.id,
        )
        _add_item(
            session,
            user_id=self.user_id,
            set_code="C-003",
            rarity_code="(UR)",
            quantity=1,
            folder_id=None,
        )
        session.commit()
        session.close()

    def tearDown(self):
        self.engine.dispose()

    def test_stats_totals_and_folders(self):
        session = self.Session()
        stats = collection_stats(session, user_id=self.user_id)
        session.close()

        self.assertEqual(stats["total_items"], 3)
        self.assertEqual(stats["total_quantity"], 6)
        self.assertEqual(stats["unique_printings"], 3)
        self.assertEqual(stats["no_folder_count"], 1)
        self.assertEqual(stats["no_folder_quantity"], 1)
        self.assertEqual(len(stats["folders"]), 1)
        self.assertEqual(stats["folders"][0]["name"], "Box 1")
        self.assertEqual(stats["folders"][0]["item_count"], 2)
        self.assertEqual(stats["folders"][0]["quantity"], 5)

    def test_empty_folder_appears_in_stats(self):
        session = self.Session()
        empty = CollectionFolder(user_id=self.user_id, name="Empty Box", name_key="empty box")
        session.add(empty)
        session.commit()

        stats = collection_stats(session, user_id=self.user_id)
        session.close()

        names = [f["name"] for f in stats["folders"]]
        self.assertIn("Empty Box", names)
        empty_stats = next(f for f in stats["folders"] if f["name"] == "Empty Box")
        self.assertEqual(empty_stats["item_count"], 0)
        self.assertEqual(empty_stats["quantity"], 0)


if __name__ == "__main__":
    unittest.main()
