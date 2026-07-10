"""Tests for search_cards tag filter."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, Card, User, UserCardTag
from ygo_app.services import add_user_tag, list_user_tags, search_cards


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


class TestSearchCardsByTag(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        session = sessionmaker(bind=self.engine)()

        session.add(User(id=1, email="user@example.com", hashed_password="hash"))
        session.add(Card(id=1, name="Tagged Card", desc=""))
        session.add(Card(id=2, name="Other Card", desc=""))
        session.commit()
        add_user_tag(session, 1, 1, "feketeleves")
        add_user_tag(session, 1, 2, "staple")
        add_user_tag(session, 1, 1, "staple")
        session.close()
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _ids(self, *, tag: str, user_id: int | None = 1) -> set[int]:
        session = self.Session()
        try:
            cards, _total = search_cards(session, tag=tag, user_id=user_id, limit=100)
            return {c.id for c in cards}
        finally:
            session.close()

    def test_tag_filter_matches_tagged_card(self):
        self.assertEqual(self._ids(tag="feketeleves"), {1})

    def test_tag_filter_case_insensitive(self):
        self.assertEqual(self._ids(tag="FEKETELEVES"), {1})

    def test_tag_filter_no_match(self):
        self.assertEqual(self._ids(tag="missing"), set())

    def test_tag_without_user_returns_empty(self):
        session = self.Session()
        try:
            cards, total = search_cards(session, tag="feketeleves", user_id=None, limit=100)
            self.assertEqual(cards, [])
            self.assertEqual(total, 0)
        finally:
            session.close()

    def test_tag_scoped_to_user(self):
        session = self.Session()
        try:
            session.add(User(id=2, email="other@example.com", hashed_password="hash"))
            session.commit()
            cards, _total = search_cards(session, tag="feketeleves", user_id=2, limit=100)
            self.assertEqual(cards, [])
        finally:
            session.close()


class TestListUserTags(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        session = sessionmaker(bind=self.engine)()

        session.add(User(id=1, email="user@example.com", hashed_password="hash"))
        session.add(User(id=2, email="other@example.com", hashed_password="hash"))
        session.add(Card(id=1, name="Card A", desc=""))
        session.add(Card(id=2, name="Card B", desc=""))
        session.commit()
        add_user_tag(session, 1, 1, "feketeleves")
        add_user_tag(session, 1, 2, "staple")
        add_user_tag(session, 1, 1, "staple")
        add_user_tag(session, 2, 2, "other-only")
        session.close()
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_list_distinct_sorted_tags(self):
        session = self.Session()
        try:
            tags = list_user_tags(session, 1)
            self.assertEqual(tags, ["feketeleves", "staple"])
        finally:
            session.close()

    def test_prefix_filter(self):
        session = self.Session()
        try:
            tags = list_user_tags(session, 1, q="fek")
            self.assertEqual(tags, ["feketeleves"])
        finally:
            session.close()

    def test_scoped_to_user(self):
        session = self.Session()
        try:
            tags = list_user_tags(session, 2)
            self.assertEqual(tags, ["other-only"])
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
