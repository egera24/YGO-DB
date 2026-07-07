"""Format-filtered search must not use runtime Python pool fallback."""

from __future__ import annotations

import tempfile
import unittest
from unittest import mock

from sqlalchemy import create_engine, delete, event, func, select
from sqlalchemy.orm import sessionmaker

from ygo_app.formats.context import resolve_format_enrich_context
from ygo_app.models import Base, Card, CardFormatLegality, Format
from ygo_app.services import enrich_cards_for_format, search_cards


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


class TestFormatSearchPerformance(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        session = sessionmaker(bind=self.engine)()

        session.add(
            Format(
                code="edison",
                name="Edison",
                description="Test format",
                uses_banlist=True,
                uses_point_list=False,
                sort_order=1,
            )
        )
        session.flush()
        session.add(Card(id=100, name="Alpha Edison Card"))
        session.add(Card(id=200, name="Beta Modern Card"))
        session.flush()
        session.add(
            CardFormatLegality(card_id=100, format_code="edison", is_legal=True)
        )
        session.commit()
        session.close()
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_search_uses_legality_table_not_python_cutoff(self):
        session = self.Session()
        try:
            with mock.patch(
                "ygo_app.formats.pool.legal_card_ids_by_cutoff",
                side_effect=AssertionError(
                    "legal_card_ids_by_cutoff must not run during search"
                ),
            ):
                cards, total = search_cards(session, format_code="edison", limit=100)
            self.assertEqual(total, 1)
            self.assertEqual([c.id for c in cards], [100])
        finally:
            session.close()

    def test_search_empty_legality_table_returns_no_results(self):
        session = self.Session()
        try:
            session.execute(delete(CardFormatLegality))
            session.commit()
            with mock.patch(
                "ygo_app.formats.pool.legal_card_ids_by_cutoff",
                side_effect=AssertionError(
                    "legal_card_ids_by_cutoff must not run during search"
                ),
            ):
                cards, total = search_cards(session, format_code="edison", limit=100)
            self.assertEqual(total, 0)
            self.assertEqual(cards, [])
        finally:
            session.close()


class TestFormatSearchEnrichment(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        session = sessionmaker(bind=self.engine)()

        session.add(
            Format(
                code="edison",
                name="Edison",
                description="Test format",
                uses_banlist=True,
                uses_point_list=False,
                sort_order=1,
            )
        )
        session.flush()
        session.add(Card(id=100, name="Alpha Edison Card"))
        session.flush()
        session.add(
            CardFormatLegality(card_id=100, format_code="edison", is_legal=True)
        )
        session.commit()
        session.close()
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_search_enrichment_skips_format_legal_queries(self):
        session = self.Session()
        try:
            card = session.get(Card, 100)
            ctx = resolve_format_enrich_context(session, "edison")
            assert ctx is not None

            before = session.execute(
                select(func.count()).select_from(CardFormatLegality)
            ).scalar()

            with mock.patch(
                "ygo_app.formats.pool.batch_card_legal_in_format",
                side_effect=AssertionError(
                    "batch_card_legal_in_format must not run for search enrichment"
                ),
            ):
                extras = enrich_cards_for_format(
                    session, [card], ctx=ctx, for_search=True
                )

            after = session.execute(
                select(func.count()).select_from(CardFormatLegality)
            ).scalar()
            self.assertEqual(before, after)
            self.assertNotIn("format_legal", extras[100])
        finally:
            session.close()

    def test_detail_enrichment_batches_format_legal(self):
        session = self.Session()
        try:
            card = session.get(Card, 100)
            ctx = resolve_format_enrich_context(session, "edison")
            assert ctx is not None

            with mock.patch(
                "ygo_app.formats.pool.card_in_pool_by_cutoff",
                side_effect=AssertionError("per-card cutoff must not run when legality row exists"),
            ):
                extras = enrich_cards_for_format(
                    session, [card], ctx=ctx, for_search=False
                )

            self.assertTrue(extras[100]["format_legal"])
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
