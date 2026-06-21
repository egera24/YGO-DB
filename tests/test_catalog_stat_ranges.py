"""Catalog stat_ranges in /filters and inverted range normalization."""

from __future__ import annotations

import json
import tempfile
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.api.routes.meta import _catalog_stat_ranges, invalidate_catalog_filters_cache
from ygo_app.models import Base, Card
from ygo_app.services import _normalize_int_range, search_cards


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


class TestCatalogStatRanges(unittest.TestCase):
    def setUp(self):
        invalidate_catalog_filters_cache()
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
                rank=4,
                atk=2600,
                def_=2100,
            )
        )
        session.add(
            Card(
                id=3,
                name="Pendulum Sorcerer",
                category="Monster",
                types=json.dumps(["Spellcaster", "Pendulum", "Effect"]),
                pendulum_scale=4,
                atk=1500,
                def_=2000,
            )
        )
        session.commit()
        session.close()
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        invalidate_catalog_filters_cache()
        self.engine.dispose()

    def test_catalog_stat_ranges_from_db(self):
        session = self.Session()
        try:
            ranges = _catalog_stat_ranges(session)
        finally:
            session.close()

        self.assertEqual(ranges["level"], {"min": 8, "max": 8})
        self.assertEqual(ranges["rank"], {"min": 4, "max": 4})
        self.assertIsNone(ranges["link_rating"])
        self.assertEqual(ranges["pendulum_scale"], {"min": 4, "max": 4})
        self.assertEqual(ranges["atk"], {"min": 1500, "max": 2800})
        self.assertEqual(ranges["def"], {"min": 2000, "max": 2100})

    def test_normalize_int_range_swaps_inverted_pair(self):
        self.assertEqual(_normalize_int_range(10000, 500), (500, 10000))
        self.assertEqual(_normalize_int_range(4, 8), (4, 8))
        self.assertEqual(_normalize_int_range(None, 500), (None, 500))

    def test_search_normalizes_inverted_atk_range(self):
        session = self.Session()
        try:
            forward, _ = search_cards(session, atk_min=500, atk_max=2800, limit=100)
            inverted, _ = search_cards(session, atk_min=2800, atk_max=500, limit=100)
        finally:
            session.close()

        self.assertEqual({c.id for c in forward}, {c.id for c in inverted})
        self.assertEqual({c.id for c in forward}, {1, 2, 3})


if __name__ == "__main__":
    unittest.main()
