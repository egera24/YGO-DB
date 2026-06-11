"""Folder entity rename for collection."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, CollectionFolder, CollectionItem, CollectionItemFolder, User
from ygo_app.services import FolderConflictError, update_collection_folder


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

        folder = CollectionFolder(
            user_id=self.user_id, name="Old Box", name_key="old box"
        )
        session.add(folder)
        session.flush()
        self.folder_id = folder.id

        for set_code in ("X-001", "X-002"):
            item = CollectionItem(
                user_id=self.user_id,
                set_code=set_code,
                rarity_code="(C)",
                quantity=1,
            )
            session.add(item)
            session.flush()
            session.add(
                CollectionItemFolder(
                    collection_item_id=item.id,
                    folder_id=folder.id,
                    quantity=1,
                )
            )
        session.commit()
        session.close()

    def tearDown(self):
        self.engine.dispose()

    def test_rename_updates_folder_entity(self):
        session = self.Session()
        folder = update_collection_folder(
            session,
            user_id=self.user_id,
            folder_id=self.folder_id,
            name="New Box",
        )
        names = session.execute(select(CollectionFolder.name)).scalars().all()
        session.close()

        self.assertEqual(folder.name, "New Box")
        self.assertEqual(folder.name_key, "new box")
        self.assertEqual(names, ["New Box"])

    def test_rename_rejects_empty_name(self):
        session = self.Session()
        with self.assertRaises(ValueError):
            update_collection_folder(
                session,
                user_id=self.user_id,
                folder_id=self.folder_id,
                name="  ",
            )
        session.close()

    def test_rename_conflict(self):
        session = self.Session()
        session.add(
            CollectionFolder(user_id=self.user_id, name="Taken", name_key="taken")
        )
        session.commit()
        with self.assertRaises(FolderConflictError):
            update_collection_folder(
                session,
                user_id=self.user_id,
                folder_id=self.folder_id,
                name="Taken",
            )
        session.close()


if __name__ == "__main__":
    unittest.main()
