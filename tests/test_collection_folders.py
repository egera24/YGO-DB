"""Collection folder CRUD."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.models import (
    Base,
    CollectionFolder,
    CollectionItem,
    CollectionItemFolder,
    User,
)
from ygo_app.services import (
    FolderConflictError,
    create_collection_folder,
    delete_collection_folder,
    get_or_create_folder,
)


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


class TestCollectionFolders(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="folders@test.example", hashed_password="x")
        session.add(user)
        session.flush()
        self.user_id = user.id
        session.commit()
        session.close()

    def tearDown(self):
        self.engine.dispose()

    def test_create_folder(self):
        session = self.Session()
        folder = create_collection_folder(session, user_id=self.user_id, name="Binder A")
        session.close()
        self.assertEqual(folder.name, "Binder A")

    def test_duplicate_folder_raises(self):
        session = self.Session()
        create_collection_folder(session, user_id=self.user_id, name="Binder A")
        with self.assertRaises(FolderConflictError):
            create_collection_folder(session, user_id=self.user_id, name="binder a")
        session.close()

    def test_get_or_create_folder_case_insensitive(self):
        session = self.Session()
        first = get_or_create_folder(session, user_id=self.user_id, name="Box 1")
        session.commit()
        second = get_or_create_folder(session, user_id=self.user_id, name="box 1")
        session.close()
        self.assertIsNotNone(first)
        self.assertEqual(first.id, second.id)

    def test_delete_folder_moves_allocations_to_no_folder(self):
        session = self.Session()
        folder = create_collection_folder(session, user_id=self.user_id, name="Box 1")
        item = CollectionItem(
            user_id=self.user_id,
            set_code="X-001",
            rarity_code="(C)",
            quantity=2,
        )
        session.add(item)
        session.flush()
        session.add(
            CollectionItemFolder(
                collection_item_id=item.id,
                folder_id=folder.id,
                quantity=2,
            )
        )
        session.commit()

        moved_allocations, moved_quantity = delete_collection_folder(
            session, user_id=self.user_id, folder_id=folder.id
        )
        folders_left = session.execute(select(CollectionFolder)).scalars().all()
        allocation = session.execute(
            select(CollectionItemFolder).where(
                CollectionItemFolder.collection_item_id == item.id
            )
        ).scalar_one()
        session.close()

        self.assertEqual(moved_allocations, 1)
        self.assertEqual(moved_quantity, 2)
        self.assertEqual(folders_left, [])
        self.assertIsNone(allocation.folder_id)
        self.assertEqual(allocation.quantity, 2)


if __name__ == "__main__":
    unittest.main()
