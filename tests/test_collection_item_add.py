"""Collection item create upsert by edition + condition."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, Card, CollectionFolder, CollectionItem, Printing, User
from ygo_app.services import add_collection_item


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


class TestCollectionItemAdd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="add@test.example", hashed_password="x")
        session.add(user)
        session.flush()
        self.user_id = user.id
        folder = CollectionFolder(
            user_id=self.user_id, name="BIN1", name_key="bin1"
        )
        session.add(folder)
        session.flush()
        self.folder_id = folder.id

        card = Card(id=89631139, name="Blue-Eyes White Dragon")
        session.add(card)
        session.add(
            Printing(
                card_id=card.id,
                set_code="LOB-001",
                set_rarity_code="(UR)",
            )
        )
        session.commit()
        session.close()

    def tearDown(self):
        self.engine.dispose()

    def _payload(self, **overrides):
        body = {
            "set_code": "LOB-001",
            "rarity": "(UR)",
            "quantity": 1,
            "printing": "Unlimited",
            "condition": "NearMint",
            "folder_id": self.folder_id,
        }
        body.update(overrides)
        return body

    def test_add_without_folder_raises(self):
        session = self.Session()
        with self.assertRaisesRegex(ValueError, "Folder is required"):
            add_collection_item(
                session,
                self.user_id,
                {
                    "set_code": "LOB-001",
                    "rarity": "(UR)",
                    "quantity": 1,
                    "printing": "Unlimited",
                    "condition": "NearMint",
                },
            )
        session.close()

    def test_add_creates_separate_rows_for_different_editions(self):
        session = self.Session()
        add_collection_item(
            session,
            self.user_id,
            self._payload(printing="1st Edition"),
        )
        add_collection_item(
            session,
            self.user_id,
            self._payload(printing="Unlimited"),
        )
        items = session.execute(
            select(CollectionItem).where(CollectionItem.user_id == self.user_id)
        ).scalars().all()
        session.close()
        self.assertEqual(len(items), 2)

    def test_add_upserts_quantity_for_matching_variant(self):
        session = self.Session()
        first = add_collection_item(
            session,
            self.user_id,
            self._payload(quantity=2),
        )
        second = add_collection_item(
            session,
            self.user_id,
            self._payload(quantity=3),
        )
        session.refresh(second)
        by_folder = {
            row.folder_id: row.quantity for row in second.folder_allocations
        }
        session.close()
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.quantity, 5)
        self.assertEqual(by_folder[self.folder_id], 5)

    def test_upsert_without_folder_raises(self):
        session = self.Session()
        add_collection_item(session, self.user_id, self._payload(quantity=1))
        with self.assertRaisesRegex(ValueError, "Folder is required"):
            add_collection_item(
                session,
                self.user_id,
                {
                    "set_code": "LOB-001",
                    "rarity": "(UR)",
                    "quantity": 1,
                    "printing": "Unlimited",
                    "condition": "NearMint",
                },
            )
        session.close()


if __name__ == "__main__":
    unittest.main()
