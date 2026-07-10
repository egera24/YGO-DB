"""HTTP streaming tests for collection CSV import progress."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.api.main import app
from ygo_app.auth import create_access_token
from ygo_app.database import get_db
from ygo_app.models import Base, Card, Printing, User


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


class TestImportCsvStreaming(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(
            email="stream@test.example",
            hashed_password="x",
            email_verified_at=datetime.utcnow(),
        )
        session.add(user)
        session.flush()
        self.user_id = user.id
        session.add(Card(id=89631139, name="Blue-Eyes White Dragon"))
        session.add(
            Printing(
                card_id=89631139,
                set_code="LOB-001",
                set_rarity_code="(UR)",
                set_rarity="Ultra Rare",
            )
        )
        session.commit()
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

        self.session_factory_patcher = patch(
            "ygo_app.import_data.SessionLocal", self.Session
        )
        self.init_db_patcher = patch("ygo_app.import_data.init_db", lambda: None)
        self.session_factory_patcher.start()
        self.init_db_patcher.start()

    def tearDown(self):
        self.init_db_patcher.stop()
        self.session_factory_patcher.stop()
        app.dependency_overrides.clear()
        self.client.close()
        self.engine.dispose()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def _parse_stream(self, body: str) -> list[dict]:
        events = []
        for line in body.splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events

    def test_stream_is_not_gzip_encoded(self):
        csv_content = (
            "Card Number,Rarity,Card Name,Quantity\n"
            "LOB-001,(UR),Blue-Eyes,1\n"
        )
        res = self.client.post(
            "/api/collection/import-csv?replace=true",
            files={"file": ("test.csv", csv_content, "text/csv")},
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("content-type"), "application/x-ndjson")
        self.assertNotIn("gzip", (res.headers.get("content-encoding") or "").lower())

    def test_stream_emits_progress_before_done(self):
        csv_content = (
            "Card Number,Rarity,Card Name,Quantity\n"
            "LOB-001,(UR),Blue-Eyes,1\n"
            "LOB-002,(SR),Missing,1\n"
        )
        res = self.client.post(
            "/api/collection/import-csv?replace=true",
            files={"file": ("test.csv", csv_content, "text/csv")},
            headers=self.auth_headers,
        )
        self.assertEqual(res.status_code, 200)
        events = self._parse_stream(res.text)
        self.assertTrue(events)
        self.assertEqual(events[0]["type"], "progress")
        self.assertEqual(events[0]["phase"], "started")
        progress_events = [ev for ev in events if ev.get("type") == "progress"]
        done_events = [ev for ev in events if ev.get("type") == "done"]
        self.assertGreater(len(progress_events), 1)
        self.assertEqual(len(done_events), 1)
        self.assertLess(
            progress_events.index(events[0]),
            events.index(done_events[0]),
        )
        importing = [ev for ev in progress_events if ev.get("phase") == "importing"]
        self.assertTrue(any(ev.get("remaining", 0) >= 0 for ev in importing))
        progress_phases = [ev.get("phase") for ev in progress_events if ev.get("phase")]
        self.assertEqual(progress_phases[-1], "finalizing")
        preload_messages = [
            ev.get("message")
            for ev in progress_events
            if ev.get("phase") == "preloading"
        ]
        self.assertIn("Scanning catalog for alternate-art codes…", preload_messages)
        self.assertEqual(done_events[0]["imported"], 1)
