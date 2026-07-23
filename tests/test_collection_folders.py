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

    def test_delete_folder_moves_allocations_to_target(self):
        session = self.Session()
        folder = create_collection_folder(session, user_id=self.user_id, name="Box 1")
        target = create_collection_folder(session, user_id=self.user_id, name="Box 2")
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

        moved_allocations, moved_quantity, removed_allocations, removed_quantity = (
            delete_collection_folder(
                session,
                user_id=self.user_id,
                folder_id=folder.id,
                target_folder_id=target.id,
            )
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
        self.assertEqual(removed_allocations, 0)
        self.assertEqual(removed_quantity, 0)
        self.assertEqual(len(folders_left), 1)
        self.assertEqual(folders_left[0].id, target.id)
        self.assertEqual(allocation.folder_id, target.id)
        self.assertEqual(allocation.quantity, 2)

    def test_delete_nonempty_folder_requires_target(self):
        session = self.Session()
        folder = create_collection_folder(session, user_id=self.user_id, name="Box 1")
        item = CollectionItem(
            user_id=self.user_id,
            set_code="X-001",
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

        with self.assertRaisesRegex(ValueError, "target_folder_id is required"):
            delete_collection_folder(
                session, user_id=self.user_id, folder_id=folder.id
            )
        session.close()

    def test_delete_folder_remove_cards_deletes_sole_item(self):
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
        item_id = item.id
        session.add(
            CollectionItemFolder(
                collection_item_id=item.id,
                folder_id=folder.id,
                quantity=2,
            )
        )
        session.commit()

        moved_allocations, moved_quantity, removed_allocations, removed_quantity = (
            delete_collection_folder(
                session,
                user_id=self.user_id,
                folder_id=folder.id,
                remove_cards=True,
            )
        )
        folders_left = session.execute(select(CollectionFolder)).scalars().all()
        item_left = session.get(CollectionItem, item_id)
        session.close()

        self.assertEqual(moved_allocations, 0)
        self.assertEqual(moved_quantity, 0)
        self.assertEqual(removed_allocations, 1)
        self.assertEqual(removed_quantity, 2)
        self.assertEqual(folders_left, [])
        self.assertIsNone(item_left)

    def test_delete_folder_remove_cards_keeps_other_folder_split(self):
        session = self.Session()
        folder_a = create_collection_folder(session, user_id=self.user_id, name="Box A")
        folder_b = create_collection_folder(session, user_id=self.user_id, name="Box B")
        item = CollectionItem(
            user_id=self.user_id,
            set_code="X-001",
            rarity_code="(C)",
            quantity=5,
        )
        session.add(item)
        session.flush()
        session.add_all(
            [
                CollectionItemFolder(
                    collection_item_id=item.id,
                    folder_id=folder_a.id,
                    quantity=2,
                ),
                CollectionItemFolder(
                    collection_item_id=item.id,
                    folder_id=folder_b.id,
                    quantity=3,
                ),
            ]
        )
        session.commit()
        item_id = item.id
        folder_b_id = folder_b.id

        _, _, removed_allocations, removed_quantity = delete_collection_folder(
            session,
            user_id=self.user_id,
            folder_id=folder_a.id,
            remove_cards=True,
        )
        item = session.get(CollectionItem, item_id)
        allocation = session.execute(
            select(CollectionItemFolder).where(
                CollectionItemFolder.collection_item_id == item_id
            )
        ).scalar_one()
        folders_left = session.execute(select(CollectionFolder)).scalars().all()
        session.close()

        self.assertEqual(removed_allocations, 1)
        self.assertEqual(removed_quantity, 2)
        self.assertEqual(item.quantity, 3)
        self.assertEqual(allocation.folder_id, folder_b_id)
        self.assertEqual(allocation.quantity, 3)
        self.assertEqual(len(folders_left), 1)
        self.assertEqual(folders_left[0].id, folder_b_id)

    def test_delete_folder_rejects_remove_cards_with_target(self):
        session = self.Session()
        folder = create_collection_folder(session, user_id=self.user_id, name="Box 1")
        target = create_collection_folder(session, user_id=self.user_id, name="Box 2")
        item = CollectionItem(
            user_id=self.user_id,
            set_code="X-001",
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

        with self.assertRaisesRegex(ValueError, "not both"):
            delete_collection_folder(
                session,
                user_id=self.user_id,
                folder_id=folder.id,
                target_folder_id=target.id,
                remove_cards=True,
            )
        session.close()


if __name__ == "__main__":
    unittest.main()
