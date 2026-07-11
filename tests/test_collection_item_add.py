"""Collection item create upsert by edition + condition."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, Card, CollectionItem, Printing, User
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

    def test_add_creates_separate_rows_for_different_editions(self):
        session = self.Session()
        add_collection_item(
            session,
            self.user_id,
            {
                "set_code": "LOB-001",
                "rarity": "(UR)",
                "quantity": 1,
                "printing": "1st Edition",
                "condition": "NearMint",
            },
        )
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
            {
                "set_code": "LOB-001",
                "rarity": "(UR)",
                "quantity": 2,
                "printing": "Unlimited",
                "condition": "NearMint",
            },
        )
        second = add_collection_item(
            session,
            self.user_id,
            {
                "set_code": "LOB-001",
                "rarity": "(UR)",
                "quantity": 3,
                "printing": "Unlimited",
                "condition": "NearMint",
            },
        )
        session.close()
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.quantity, 5)


if __name__ == "__main__":
    unittest.main()
