"""Folder allocation splits on collection items."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, CollectionFolder, CollectionItem, CollectionItemFolder, User
from ygo_app.services import set_item_folder_allocations, update_collection_item


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


class TestCollectionFolderAllocations(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="alloc@test.example", hashed_password="x")
        session.add(user)
        session.flush()
        self.user_id = user.id

        self.folder_a = CollectionFolder(
            user_id=self.user_id, name="Binder A", name_key="binder a"
        )
        self.folder_b = CollectionFolder(
            user_id=self.user_id, name="Box 1", name_key="box 1"
        )
        session.add_all([self.folder_a, self.folder_b])
        session.flush()

        item = CollectionItem(
            user_id=self.user_id,
            set_code="LOB-001",
            rarity_code="(UR)",
            quantity=3,
        )
        session.add(item)
        session.flush()
        self.item_id = item.id
        self.folder_a_id = self.folder_a.id
        self.folder_b_id = self.folder_b.id
        session.add(
            CollectionItemFolder(
                collection_item_id=item.id,
                folder_id=self.folder_a.id,
                quantity=3,
            )
        )
        session.commit()
        session.close()

    def tearDown(self):
        self.engine.dispose()

    def test_split_across_two_folders(self):
        session = self.Session()
        item = session.get(CollectionItem, self.item_id)
        set_item_folder_allocations(
            session,
            user_id=self.user_id,
            item=item,
            allocations=[
                {"folder_id": self.folder_a_id, "quantity": 2},
                {"folder_id": self.folder_b_id, "quantity": 1},
            ],
        )
        session.commit()
        session.refresh(item)
        quantities = sorted(row.quantity for row in item.folder_allocations)
        session.close()
        self.assertEqual(quantities, [1, 2])

    def test_allocation_sum_validation(self):
        session = self.Session()
        item = session.get(CollectionItem, self.item_id)
        with self.assertRaises(ValueError):
            set_item_folder_allocations(
                session,
                user_id=self.user_id,
                item=item,
                allocations=[
                    {"folder_id": self.folder_a_id, "quantity": 1},
                    {"folder_id": self.folder_b_id, "quantity": 1},
                ],
            )
        session.close()

    def test_copy_increases_quantity_with_allocations(self):
        """Copy-shaped PATCH: raise total quantity and allocate the new copies."""
        session = self.Session()
        item = session.get(CollectionItem, self.item_id)
        update_collection_item(
            session,
            user_id=self.user_id,
            item=item,
            data={
                "quantity": 13,
                "folder_allocations": [
                    {"folder_id": self.folder_a_id, "quantity": 3},
                    {"folder_id": self.folder_b_id, "quantity": 10},
                ],
            },
        )
        session.refresh(item)
        by_folder = {
            row.folder_id: row.quantity for row in item.folder_allocations
        }
        quantity = item.quantity
        session.close()
        self.assertEqual(quantity, 13)
        self.assertEqual(by_folder[self.folder_a_id], 3)
        self.assertEqual(by_folder[self.folder_b_id], 10)

    def test_update_item_with_folder_allocations(self):
        session = self.Session()
        item = session.get(CollectionItem, self.item_id)
        update_collection_item(
            session,
            user_id=self.user_id,
            item=item,
            data={
                "folder_allocations": [
                    {"folder_id": None, "quantity": 1},
                    {"folder_id": self.folder_b_id, "quantity": 2},
                ]
            },
        )
        session.refresh(item)
        by_folder = {
            row.folder_id: row.quantity for row in item.folder_allocations
        }
        session.close()
        self.assertEqual(by_folder[None], 1)
        self.assertEqual(by_folder[self.folder_b_id], 2)


if __name__ == "__main__":
    unittest.main()
