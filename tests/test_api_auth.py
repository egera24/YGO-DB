"""HTTP auth enforcement on catalog/meta read routes."""

from __future__ import annotations

import os
import tempfile
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.api.main import app
from ygo_app.auth import create_access_token
from ygo_app.database import get_db
from ygo_app.models import Base, Card, User


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


class TestApiAuth(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="auth@test.example", hashed_password="x")
        session.add(user)
        session.add(
            Card(
                id=89631139,
                name="Blue-Eyes White Dragon",
                category="Monster",
                attribute="LIGHT",
                types='["Normal"]',
            )
        )
        session.commit()
        self.user_id = user.id
        session.close()

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.auth_headers = {
            "Authorization": f"Bearer {create_access_token(self.user_id)}"
        }

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_health_public_without_auth(self):
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True})

    def test_protected_routes_return_401_without_auth(self):
        for path in (
            "/api/filters",
            "/api/status",
            "/api/cards/search",
            "/api/cards/summoning-suggestions?q=test",
        ):
            with self.subTest(path=path):
                res = self.client.get(path)
                self.assertEqual(res.status_code, 401, res.text)

    def test_protected_routes_return_200_with_auth(self):
        for path in (
            "/api/filters",
            "/api/status",
            "/api/cards/search",
            "/api/cards/summoning-suggestions?q=test",
        ):
            with self.subTest(path=path):
                res = self.client.get(path, headers=self.auth_headers)
                self.assertEqual(res.status_code, 200, res.text)


if __name__ == "__main__":
    unittest.main()
