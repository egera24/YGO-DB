"""Integration tests for search_cards text matching."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, Card
from ygo_app.services import search_cards


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


class TestSearchCards(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        session = sessionmaker(bind=self.engine)()

        session.add(
            Card(
                id=1,
                name="Shield of the Millennium Dynasty",
                desc=(
                    "Cannot be destroyed by Spell/Trap effects. If this card is in your hand: "
                    "You can reveal 1 Millennium Ankh in your hand; Special Summon this card."
                ),
            )
        )
        session.add(
            Card(
                id=2,
                name="Scattered Words",
                desc="You can. Reveal this card for a different effect.",
            )
        )
        session.add(
            Card(
                id=3,
                name="No Match",
                desc="This card does nothing relevant.",
            )
        )
        session.commit()
        session.close()
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _ids(self, q: str) -> set[int]:
        session = self.Session()
        try:
            cards, _total = search_cards(session, q=q, limit=100)
            return {c.id for c in cards}
        finally:
            session.close()

    def test_single_word(self):
        self.assertIn(1, self._ids("reveal"))
        self.assertIn(2, self._ids("reveal"))
        self.assertNotIn(3, self._ids("reveal"))

    def test_phrase_requires_contiguous_text(self):
        self.assertIn(1, self._ids('"You can reveal"'))
        self.assertNotIn(2, self._ids('"You can reveal"'))

    def test_phrase_case_insensitive(self):
        self.assertIn(1, self._ids('"you can reveal"'))

    def test_not_excludes(self):
        self.assertIn(1, self._ids("reveal -different"))
        self.assertNotIn(2, self._ids("reveal -different"))

    def test_passcode_numeric(self):
        self.assertEqual(self._ids("1"), {1})


if __name__ == "__main__":
    unittest.main()
