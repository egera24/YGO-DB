"""Catalog full-replace import must not break collection_items FK to printings."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.import_data import import_cards_entries
from ygo_app.models import Base, Card, CollectionItem, Printing, User


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


class TestImportCatalogReplace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="test@example.com", hashed_password="x")
        session.add(user)
        session.flush()

        card = Card(id=999, name="Old Card")
        session.add(card)
        session.flush()

        printing = Printing(
            card_id=card.id,
            set_code="LOB-001",
            set_rarity="Ultra Rare",
            set_rarity_code="(UR)",
        )
        session.add(printing)
        session.flush()

        session.add(
            CollectionItem(
                user_id=user.id,
                set_code="LOB-001",
                rarity_code="(UR)",
                quantity=2,
                printing_id=printing.id,
            )
        )
        session.commit()
        self.old_card_id = card.id
        session.close()

        self.session_factory_patcher = patch(
            "ygo_app.import_data.SessionLocal", self.Session
        )
        self.init_db_patcher = patch("ygo_app.import_data.init_db", lambda: None)
        self.search_patcher = patch(
            "ygo_app.import_data.rebuild_search_index", lambda _session: None
        )
        self.session_factory_patcher.start()
        self.init_db_patcher.start()
        self.search_patcher.start()

    def tearDown(self):
        self.search_patcher.stop()
        self.init_db_patcher.stop()
        self.session_factory_patcher.stop()
        self.engine.dispose()

    def test_import_replaces_catalog_and_preserves_collection_links(self):
        entries = [
            {
                "id": 12345,
                "name": "New Card",
                "card_sets": [
                    {
                        "set_code": "LOB-001",
                        "set_name": "Legend of Blue Eyes",
                        "set_rarity": "Ultra Rare",
                        "set_rarity_code": "UR",
                    }
                ],
            }
        ]
        cards, printings = import_cards_entries(entries)

        self.assertEqual(cards, 1)
        self.assertEqual(printings, 1)

        session = self.Session()
        try:
            item = session.query(CollectionItem).one()
            self.assertEqual(item.quantity, 2)
            self.assertEqual(item.set_code, "LOB-001")
            self.assertIsNotNone(item.printing_id)

            self.assertIsNone(session.get(Card, self.old_card_id))

            printing = session.get(Printing, item.printing_id)
            self.assertIsNotNone(printing)
            assert printing is not None
            # printing_id may reuse the same autoincrement after full replace
            self.assertEqual(printing.card_id, 12345)
            self.assertEqual(printing.set_code, "LOB-001")
            self.assertEqual(printing.set_rarity_code, "(UR)")
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
