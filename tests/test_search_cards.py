"""Integration tests for search_cards text matching."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, Card, User, UserCardTag
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
                passcode=88888888,
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
                passcode=2,
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
        session.add(
            Card(
                id=4,
                passcode=89631139,
                name="Number 39: Utopia",
                desc="A number of monsters can attack.",
                mechanic="Xyz",
                atk=2500,
                level=4,
            )
        )
        session.add(
            Card(
                id=5,
                passcode=5,
                name="Low ATK Monster",
                desc="Weak monster.",
                atk=500,
                level=2,
            )
        )
        session.add(User(id=1, email="test@example.com", hashed_password="x"))
        session.add(UserCardTag(user_id=1, card_id=4, tag="staple"))
        session.commit()
        session.close()
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _ids(self, q: str, *, user_id: int | None = None) -> set[int]:
        session = self.Session()
        try:
            cards, _total = search_cards(session, q=q, limit=100, user_id=user_id)
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
        self.assertEqual(self._ids("88888888"), {1})
        self.assertEqual(self._ids("2"), {2})

    def test_passcode_numeric_surrogate_id_not_matched(self):
        self.assertEqual(self._ids("1"), set())

    def test_case_sensitive_name(self):
        self.assertEqual(self._ids("name:=Number"), {4})
        self.assertEqual(self._ids("name:number"), {4})
        self.assertEqual(self._ids("name:=number"), set())

    def test_name_field_excludes_desc_only_match(self):
        self.assertEqual(self._ids("name:=Number"), {4})
        self.assertIn(4, self._ids("desc:number"))
        self.assertNotIn(4, self._ids("name:=number"))

    def test_atk_range(self):
        self.assertEqual(self._ids("atk:>=2500"), {4})
        self.assertEqual(self._ids("atk:1000..3000"), {4})
        self.assertNotIn(5, self._ids("atk:>=2500"))

    def test_level_exact(self):
        self.assertEqual(self._ids("level:4"), {4})
        self.assertNotIn(5, self._ids("level:4"))

    def test_passcode_in_compound_query(self):
        self.assertEqual(self._ids("passcode:89631139"), {4})
        self.assertEqual(self._ids("name:Utopia passcode:89631139"), {4})

    def test_mechanic_field(self):
        self.assertEqual(self._ids("mechanic:Xyz"), {4})

    def test_tag_field_requires_user(self):
        self.assertEqual(self._ids("tag:staple", user_id=1), {4})
        self.assertEqual(self._ids("tag:staple"), set())

    def test_compound_case_sensitive_with_mechanic(self):
        self.assertEqual(self._ids("name:=Number mechanic:Xyz"), {4})


if __name__ == "__main__":
    unittest.main()
