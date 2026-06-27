"""GET /api/collection/{item_id} — single collection item read."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.api.main import app
from ygo_app.auth import create_access_token
from ygo_app.database import get_db
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


class TestGetCollectionItem(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        owner = User(
            email="owner@test.example",
            hashed_password="x",
            email_verified_at=datetime.utcnow(),
        )
        other = User(
            email="other@test.example",
            hashed_password="x",
            email_verified_at=datetime.utcnow(),
        )
        session.add_all([owner, other])
        session.flush()
        self.owner_id = owner.id
        self.other_id = other.id

        card = Card(id=89631139, name="Blue-Eyes White Dragon")
        session.add(card)
        session.add(
            Printing(
                card_id=card.id,
                set_code="LOB-001",
                set_rarity_code="(UR)",
                set_rarity="Ultra Rare",
            )
        )
        session.flush()

        item = CollectionItem(
            user_id=self.owner_id,
            set_code="LOB-001",
            rarity_code="(UR)",
            card_name=card.name,
            quantity=2,
            trade_quantity=1,
        )
        session.add(item)
        session.commit()
        self.item_id = item.id
        session.close()

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.owner_headers = {
            "Authorization": f"Bearer {create_access_token(self.owner_id)}"
        }
        self.other_headers = {
            "Authorization": f"Bearer {create_access_token(self.other_id)}"
        }

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_get_collection_item_returns_owner_row(self):
        res = self.client.get(
            f"/api/collection/{self.item_id}",
            headers=self.owner_headers,
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["id"], self.item_id)
        self.assertEqual(data["set_code"], "LOB-001")
        self.assertEqual(data["quantity"], 2)
        self.assertEqual(data["trade_quantity"], 1)

    def test_get_collection_item_404_for_other_user(self):
        res = self.client.get(
            f"/api/collection/{self.item_id}",
            headers=self.other_headers,
        )
        self.assertEqual(res.status_code, 404, res.text)

    def test_get_collection_item_404_when_missing(self):
        res = self.client.get(
            "/api/collection/999999",
            headers=self.owner_headers,
        )
        self.assertEqual(res.status_code, 404, res.text)


if __name__ == "__main__":
    unittest.main()
