"""Tests for Skill Card discovery, parsing metadata, and import."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.import_data import import_cards_entries
from ygo_app.models import Base, Card
from ygo_app.yugipedia.card_import import yugipedia_entry_to_import
from ygo_app.yugipedia.passcodes import _merge_skill_cards
from ygo_app.yugipedia.parsing import parse_skill_card
from ygo_app.yugipedia.skill_cards import get_skill_cards_in_batch

SKILL_HTML = """
<html><body>
<table class="infobox">
  <tr><th>Card type</th><td><a href="/wiki/Skill_Card">Skill</a></td></tr>
  <tr><th>Types</th><td><a href="/wiki/Seto_Kaiba">Kaiba</a> / <a href="/wiki/Skill_Card">Skill</a></td></tr>
  <tr><th>Property</th><td><a href="/wiki/Normal">Normal</a></td></tr>
</table>
<div class="lore"><p>Skill effect text here.</p></div>
<table id="cts--EN" class="card-list">
  <tbody>
    <tr><td>2019-01-01</td><td><a href="/wiki/SBLS-ENS01">SBLS-ENS01</a></td>
        <td><a href="/wiki/Set"><i>Speed Duel Starter Decks</i></a></td>
        <td><a href="/wiki/Common">Common</a></td></tr>
  </tbody>
</table>
</body></html>
"""


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class TestSkillDiscovery(unittest.TestCase):
    @patch("ygo_app.yugipedia.skill_cards.time.sleep", lambda *_: None)
    def test_ask_batch_parses_character_and_urls(self):
        data = {
            "query": {
                "results": {
                    "Beatdown!": {
                        "fullurl": "https://yugipedia.com/wiki/Beatdown!",
                        "printouts": {
                            "English name": ["Beatdown!"],
                            "Card type": [
                                {
                                    "fulltext": "Skill Card",
                                    "fullurl": "https://yugipedia.com/wiki/Skill_Card",
                                }
                            ],
                            "Password": [],
                            "Character": [
                                {
                                    "fulltext": "Seto Kaiba",
                                    "fullurl": "https://yugipedia.com/wiki/Seto_Kaiba",
                                }
                            ],
                            "Property": [],
                        },
                    }
                }
            }
        }
        session = MagicMock()
        session.get.return_value = _FakeResp(data)

        cards = get_skill_cards_in_batch(session, "https://yugipedia.com/api.php", offset=0)

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["name"], "Beatdown!")
        self.assertEqual(cards[0]["card_type"], "Skill Card")
        self.assertEqual(cards[0]["url"], "https://yugipedia.com/wiki/Beatdown!")
        self.assertTrue(cards[0]["passwordless"])
        self.assertEqual(cards[0]["character"], "Seto Kaiba")
        self.assertNotIn("property", cards[0])

    @patch("ygo_app.yugipedia.skill_cards.time.sleep", lambda *_: None)
    def test_ask_pagination_returns_empty_on_missing_query(self):
        session = MagicMock()
        session.get.return_value = _FakeResp({})

        cards = get_skill_cards_in_batch(session, "https://yugipedia.com/api.php", offset=500)
        self.assertEqual(cards, [])


class TestMergeSkillCards(unittest.TestCase):
    @patch("ygo_app.yugipedia.skill_cards.fetch_skill_cards")
    def test_dedupes_by_url(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "name": "Beatdown!",
                "card_type": "Skill Card",
                "password": "",
                "url": "https://yugipedia.com/wiki/Beatdown!",
                "passwordless": True,
                "character": "Seto Kaiba",
            },
            {
                "name": "Advent of Ra",
                "card_type": "Skill Card",
                "password": "",
                "url": "https://yugipedia.com/wiki/Advent_of_Ra",
                "passwordless": True,
                "character": "Yami Marik",
            },
        ]
        existing = [
            {
                "name": "Beatdown!",
                "card_type": "Skill Card",
                "password": "",
                "url": "https://yugipedia.com/wiki/Beatdown!",
                "passwordless": True,
            }
        ]

        _merge_skill_cards(existing, max_cards=None)

        self.assertEqual(len(existing), 2)
        self.assertEqual(existing[1]["name"], "Advent of Ra")
        self.assertEqual(existing[1]["character"], "Yami Marik")


class TestParseSkillMetadata(unittest.TestCase):
    def test_character_and_property_carried_from_input(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(SKILL_HTML, "html.parser")
        input_card = {
            "name": "Beatdown!",
            "card_type": "Skill Card",
            "password": "",
            "url": "https://yugipedia.com/wiki/Beatdown!",
            "passwordless": True,
            "character": "Seto Kaiba",
            "property": "FromAsk",
        }
        card_data, error = parse_skill_card(soup, input_card)

        self.assertIsNone(error)
        assert card_data is not None
        self.assertEqual(card_data["character"], "Seto Kaiba")
        self.assertEqual(card_data["property"], "Normal")
        self.assertIn("SBLS-ENS01", [cs["set_code"] for cs in card_data.get("card_sets", [])])


def _sqlite_engine(path: str):
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _pragma(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return eng


class TestSkillImport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self._p1 = patch("ygo_app.import_data.SessionLocal", self.Session)
        self._p2 = patch("ygo_app.import_data.init_db", lambda: None)
        self._p1.start()
        self._p2.start()

    def tearDown(self):
        self._p2.stop()
        self._p1.stop()
        self.engine.dispose()

    def test_import_row_includes_character(self):
        entry = {
            "id": None,
            "source_url": "https://yugipedia.com/wiki/Beatdown!",
            "name": "Beatdown!",
            "type": "Skill",
            "property": "Normal",
            "character": "Seto Kaiba",
            "category": "Skill",
            "description": "Skill effect text here.",
            "card_sets": [
                {
                    "set_code": "SBLS-ENS01",
                    "set_name": "Speed Duel Starter Decks",
                    "set_rarity": "Common",
                    "set_rarity_code": "C",
                }
            ],
        }
        mapped = yugipedia_entry_to_import(entry)
        assert mapped is not None
        self.assertEqual(mapped["character"], "Seto Kaiba")

        cards, printings = import_cards_entries([mapped])
        self.assertEqual(cards, 1)
        self.assertEqual(printings, 1)

        session = self.Session()
        try:
            row = session.query(Card).filter(Card.name == "Beatdown!").one()
            self.assertEqual(row.character, "Seto Kaiba")
            self.assertEqual(row.category, "Skill")
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
