"""Bulk folder rename for collection items."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, CollectionItem, User
from ygo_app.services import rename_collection_folder


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


class TestCollectionFolderRename(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        self.user = User(email="rename@test.example", hashed_password="x")
        other = User(email="other@test.example", hashed_password="x")
        session.add_all([self.user, other])
        session.flush()
        self.user_id = self.user.id
        self.other_user_id = other.id

        session.add(
            CollectionItem(
                user_id=self.user_id,
                set_code="X-001",
                rarity_code="(C)",
                folder_name="Old Box",
            )
        )
        session.add(
            CollectionItem(
                user_id=self.user_id,
                set_code="X-002",
                rarity_code="(R)",
                folder_name="Old Box",
            )
        )
        session.add(
            CollectionItem(
                user_id=self.other_user_id,
                set_code="X-003",
                rarity_code="(C)",
                folder_name="Old Box",
            )
        )
        session.commit()
        session.close()

    def tearDown(self):
        self.engine.dispose()

    def test_rename_updates_only_current_user(self):
        session = self.Session()
        updated = rename_collection_folder(
            session,
            user_id=self.user_id,
            from_name="Old Box",
            to_name="New Box",
        )
        folders = session.execute(
            select(CollectionItem.folder_name, CollectionItem.user_id)
        ).all()
        session.close()

        self.assertEqual(updated, 2)
        self.assertEqual(
            sorted(f for f, uid in folders if uid == self.user_id),
            ["New Box", "New Box"],
        )
        self.assertEqual(
            [f for f, uid in folders if uid == self.other_user_id],
            ["Old Box"],
        )

    def test_rename_rejects_empty_names(self):
        session = self.Session()
        with self.assertRaises(ValueError):
            rename_collection_folder(
                session,
                user_id=self.user_id,
                from_name="  ",
                to_name="New Box",
            )
        session.close()


if __name__ == "__main__":
    unittest.main()
