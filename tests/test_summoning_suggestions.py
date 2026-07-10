"""Tests for summoning condition suggestion helper."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, Card
from ygo_app.services import summoning_condition_suggestions


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


class TestSummoningSuggestions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        session = sessionmaker(bind=self.engine)()
        session.add(
            Card(
                id=1,
                name="A",
                summoning_condition="2 Level 4 WATER monsters",
            )
        )
        session.add(
            Card(
                id=2,
                name="B",
                summoning_condition="1 Tuner + 1+ non-Tuners",
            )
        )
        session.commit()
        session.close()
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_keyword_anywhere(self):
        session = self.Session()
        try:
            rows = summoning_condition_suggestions(session, q="WATER")
            self.assertIn("2 Level 4 WATER monsters", rows)
            self.assertEqual(len(rows), 1)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
