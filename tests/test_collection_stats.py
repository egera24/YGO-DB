"""Collection stats aggregates."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, CollectionItem, User
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

        session.add(
            CollectionItem(
                user_id=self.user_id,
                set_code="A-001",
                rarity_code="(C)",
                quantity=3,
                folder_name="Box 1",
            )
        )
        session.add(
            CollectionItem(
                user_id=self.user_id,
                set_code="B-002",
                rarity_code="(R)",
                quantity=2,
                folder_name="Box 1",
            )
        )
        session.add(
            CollectionItem(
                user_id=self.user_id,
                set_code="C-003",
                rarity_code="(UR)",
                quantity=1,
                folder_name="",
            )
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
        self.assertEqual(stats["unassigned_count"], 1)
        self.assertEqual(stats["unassigned_quantity"], 1)
        self.assertEqual(len(stats["folders"]), 1)
        self.assertEqual(stats["folders"][0]["name"], "Box 1")
        self.assertEqual(stats["folders"][0]["item_count"], 2)
        self.assertEqual(stats["folders"][0]["quantity"], 5)


if __name__ == "__main__":
    unittest.main()
