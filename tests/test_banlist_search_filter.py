"""Tests for banlist status search filter."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.formats.banlist import (
    STATUS_FORBIDDEN,
    STATUS_LIMITED,
    STATUS_SEMI_LIMITED,
    parse_banlist_status_param,
)
from ygo_app.models import BanlistEntry, BanlistRevision, Base, Card, Format
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


class TestParseBanlistStatusParam(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(parse_banlist_status_param(None), [])
        self.assertEqual(parse_banlist_status_param(""), [])
        self.assertEqual(parse_banlist_status_param("  "), [])

    def test_snake_case(self):
        self.assertEqual(
            parse_banlist_status_param("forbidden,limited,semi_limited"),
            [STATUS_FORBIDDEN, STATUS_LIMITED, STATUS_SEMI_LIMITED],
        )

    def test_display_labels(self):
        self.assertEqual(
            parse_banlist_status_param("Forbidden,Limited,Semi-Limited"),
            [STATUS_FORBIDDEN, STATUS_LIMITED, STATUS_SEMI_LIMITED],
        )

    def test_deduplicates(self):
        self.assertEqual(
            parse_banlist_status_param("forbidden,Forbidden"),
            [STATUS_FORBIDDEN],
        )

    def test_ignores_unknown(self):
        self.assertEqual(parse_banlist_status_param("forbidden,unknown"), [STATUS_FORBIDDEN])


class TestBanlistStatusSearchFilter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        session = sessionmaker(bind=self.engine)()

        session.add(
            Format(
                code="advanced",
                name="Advanced TCG",
                description="Test",
                uses_banlist=True,
                uses_point_list=False,
                sort_order=1,
            )
        )
        session.add(Card(id=1, name="Forbidden Card"))
        session.add(Card(id=2, name="Limited Card"))
        session.add(Card(id=3, name="Semi-Limited Card"))
        session.add(Card(id=4, name="Unrestricted Card"))
        session.flush()

        revision = BanlistRevision(
            source_list_id="current",
            label="May 2026",
            effective_from=date(2026, 5, 18),
            fetched_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
        )
        session.add(revision)
        session.flush()

        session.add_all(
            [
                BanlistEntry(
                    revision_id=revision.id,
                    card_id=1,
                    card_name_raw="Forbidden Card",
                    status=STATUS_FORBIDDEN,
                ),
                BanlistEntry(
                    revision_id=revision.id,
                    card_id=2,
                    card_name_raw="Limited Card",
                    status=STATUS_LIMITED,
                ),
                BanlistEntry(
                    revision_id=revision.id,
                    card_id=3,
                    card_name_raw="Semi-Limited Card",
                    status=STATUS_SEMI_LIMITED,
                ),
            ]
        )
        session.commit()
        self.revision_id = revision.id
        session.close()
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _ids(self, **kwargs) -> set[int]:
        session = self.Session()
        try:
            cards, _total = search_cards(session, limit=100, **kwargs)
            return {c.id for c in cards}
        finally:
            session.close()

    def test_forbidden_only(self):
        self.assertEqual(
            self._ids(format_code="advanced", banlist_status="forbidden"),
            {1},
        )

    def test_display_label_param(self):
        self.assertEqual(
            self._ids(format_code="advanced", banlist_status="Forbidden"),
            {1},
        )

    def test_multi_status_or(self):
        self.assertEqual(
            self._ids(format_code="advanced", banlist_status="forbidden,limited"),
            {1, 2},
        )

    def test_semi_limited(self):
        self.assertEqual(
            self._ids(format_code="advanced", banlist_status="Semi-Limited"),
            {3},
        )

    def test_no_match_when_status_not_on_list(self):
        self.assertEqual(
            self._ids(format_code="advanced", banlist_status="forbidden", q="Unrestricted"),
            set(),
        )

    def test_ignored_without_format(self):
        self.assertEqual(
            self._ids(banlist_status="forbidden"),
            {1, 2, 3, 4},
        )

    def test_no_revision_returns_empty(self):
        session = self.Session()
        try:
            session.query(BanlistRevision).delete()
            session.commit()
        finally:
            session.close()
        session = self.Session()
        try:
            cards, total = search_cards(
                session,
                format_code="advanced",
                banlist_status="forbidden",
                limit=100,
            )
            self.assertEqual(cards, [])
            self.assertEqual(total, 0)
        finally:
            session.close()

    def test_respects_explicit_revision(self):
        session = self.Session()
        try:
            old = BanlistRevision(
                source_list_id="20200101",
                label="January 2020",
                effective_from=date(2020, 1, 1),
                fetched_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            )
            session.add(old)
            session.flush()
            old_id = old.id
            session.add(
                BanlistEntry(
                    revision_id=old_id,
                    card_id=4,
                    card_name_raw="Unrestricted Card",
                    status=STATUS_FORBIDDEN,
                )
            )
            session.commit()
        finally:
            session.close()

        self.assertEqual(
            self._ids(
                format_code="advanced",
                banlist_status="forbidden",
                banlist_revision_id=old_id,
            ),
            {4},
        )


if __name__ == "__main__":
    unittest.main()
