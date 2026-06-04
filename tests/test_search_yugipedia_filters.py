"""Tests for Yugipedia-native search_cards filters."""

from __future__ import annotations

import json
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


class TestSearchYugipediaFilters(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        session = sessionmaker(bind=self.engine)()

        session.add(
            Card(
                id=1,
                name="Fusion Fiend",
                category="Monster",
                types=json.dumps(["Fiend", "Fusion", "Effect"]),
                mechanic="Fusion",
                attribute="DARK",
                level=8,
                atk=2800,
                def_=2000,
            )
        )
        session.add(
            Card(
                id=2,
                name="Bahamut Shark",
                category="Monster",
                types=json.dumps(["Sea Serpent", "Xyz", "Effect"]),
                mechanic="Xyz",
                attribute="WATER",
                rank=4,
                atk=2600,
                def_=2100,
                summoning_condition="2 Level 4 WATER monsters",
            )
        )
        session.add(
            Card(
                id=3,
                name="Quick Teleport",
                category="Spell",
                types=json.dumps(["Quick-Play"]),
                archetype="Teleport",
            )
        )
        session.add(
            Card(
                id=4,
                name="Firewall Dragon",
                category="Monster",
                types=json.dumps(["Cyberse", "Link", "Effect"]),
                mechanic="Link",
                link_rating=3,
                link_markers=json.dumps(["Top", "Left", "Right"]),
                atk=2300,
            )
        )
        session.commit()
        session.close()
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _ids(self, **kwargs) -> set[int]:
        session = self.Session()
        try:
            cards, _ = search_cards(session, limit=100, **kwargs)
            return {c.id for c in cards}
        finally:
            session.close()

    def test_types_or(self):
        self.assertEqual(self._ids(types="Fusion,Normal"), {1})

    def test_category(self):
        self.assertEqual(self._ids(category="Spell"), {3})

    def test_rank_interval(self):
        self.assertEqual(self._ids(rank_min=4, rank_max=4), {2})

    def test_atk_interval(self):
        self.assertEqual(self._ids(atk_min=2800, atk_max=2800), {1})

    def test_summoning_condition(self):
        self.assertEqual(self._ids(summoning_condition="Level 4 WATER"), {2})

    def test_link_markers_and(self):
        self.assertEqual(self._ids(link_markers="Top,Left"), {4})
        self.assertEqual(self._ids(link_markers="Top,Left,Bottom"), set())


if __name__ == "__main__":
    unittest.main()
