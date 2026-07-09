"""Tests for cards printed without a passcode (discovery, parsing, mapping, import)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.import_data import import_cards_entries
from ygo_app.models import Base, Card, Printing
from ygo_app.yugipedia.adapter import yugipedia_card_to_api
from ygo_app.yugipedia.category_members import get_category_members
from ygo_app.yugipedia.parsing import extract_card_type_from_page, parse_card_page

FIXTURES = Path(__file__).parent / "fixtures" / "yugipedia"

TOKEN_HTML = """
<html><body>
<table class="infobox">
  <tr><th>Card type</th><td><a href="/wiki/Monster_Card">Monster</a></td></tr>
  <tr><th>Types</th><td><a href="/wiki/Fiend">Fiend</a> / <a href="/wiki/Token">Token</a></td></tr>
  <tr><th>Attribute</th><td><a href="/wiki/DARK">DARK</a></td></tr>
  <tr><th>Level</th><td><a href="/wiki/Level_1">1</a></td></tr>
  <tr><th>ATK / DEF</th><td><a href="/wiki/ATK">0</a> / <a href="/wiki/DEF">0</a></td></tr>
  <tr><th>Password</th><td>None</td></tr>
</table>
<table id="cts--EN" class="card-list">
  <tbody>
    <tr><td>2018-01-01</td><td><a href="/wiki/TOKEN-EN001">TOKEN-EN001</a></td>
        <td><a href="/wiki/Set"><i>Some Set</i></a></td>
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


class TestCategoryDiscovery(unittest.TestCase):
    @patch("ygo_app.yugipedia.category_members.time.sleep", lambda *_: None)
    def test_paginates_and_builds_urls(self):
        page1 = {
            "query": {"categorymembers": [{"title": "Obelisk the Tormentor", "ns": 0}]},
            "continue": {"cmcontinue": "PAGE2"},
        }
        page2 = {
            "query": {"categorymembers": [{"title": "Slifer the Sky Dragon", "ns": 0}]},
        }
        session = MagicMock()
        session.get.side_effect = [_FakeResp(page1), _FakeResp(page2)]

        members = get_category_members(session)

        self.assertEqual(len(members), 2)
        self.assertEqual(members[0]["name"], "Obelisk the Tormentor")
        self.assertEqual(
            members[0]["url"], "https://yugipedia.com/wiki/Obelisk_the_Tormentor"
        )
        self.assertTrue(all(m["passwordless"] for m in members))
        self.assertTrue(all(m["password"] == "" for m in members))


class TestParsePasswordless(unittest.TestCase):
    def test_obelisk_parses_without_password(self):
        html = (FIXTURES / "obelisk_passwordless.html").read_text(encoding="utf-8")
        input_card = {
            "name": "Obelisk the Tormentor",
            "card_type": "",
            "password": "",
            "url": "https://yugipedia.com/wiki/Obelisk_the_Tormentor",
            "passwordless": True,
        }
        card_data, error = parse_card_page(html, input_card)

        self.assertIsNone(error)
        assert card_data is not None
        self.assertIsNone(card_data["id"])
        self.assertTrue(card_data.get("passwordless"))
        self.assertEqual(
            card_data["source_url"],
            "https://yugipedia.com/wiki/Obelisk_the_Tormentor",
        )
        codes = [cs["set_code"] for cs in card_data.get("card_sets", [])]
        self.assertIn("JUMP-EN037", codes)

    def test_token_detected_as_monster(self):
        self.assertEqual(
            extract_card_type_from_page(_soup(TOKEN_HTML)), "Monster Card"
        )
        input_card = {
            "name": "Fiend Token",
            "card_type": "",
            "password": "",
            "url": "https://yugipedia.com/wiki/Fiend_Token",
            "passwordless": True,
        }
        card_data, error = parse_card_page(TOKEN_HTML, input_card)
        self.assertIsNone(error)
        assert card_data is not None
        self.assertIsNone(card_data["id"])
        self.assertEqual(card_data["category"], "Token")
        self.assertIn("TOKEN-EN001", [cs["set_code"] for cs in card_data.get("card_sets", [])])

    def test_hippo_token_card_type_row_is_token(self):
        """Yugipedia token pages list Card type as Token (not Monster)."""
        html = (FIXTURES / "hippo_token.html").read_text(encoding="utf-8")
        self.assertEqual(extract_card_type_from_page(_soup(html)), "Token Card")
        input_card = {
            "name": "Hippo Token",
            "card_type": "",
            "password": "",
            "url": "https://yugipedia.com/wiki/Hippo_Token",
            "passwordless": True,
        }
        card_data, error = parse_card_page(html, input_card)
        self.assertIsNone(error)
        assert card_data is not None
        self.assertEqual(card_data["category"], "Token")
        self.assertEqual(card_data["type"], "Beast")
        self.assertIn("Token", card_data.get("typeline", []))
        self.assertIn("YS16-ENT01", [cs["set_code"] for cs in card_data.get("card_sets", [])])

    def test_token_card_type_labels_from_passcode_list(self):
        """SMW/page labels like Token or Monster Token must route to token parsing."""
        html = (FIXTURES / "hippo_token.html").read_text(encoding="utf-8")
        base = {
            "name": "Hippo Token",
            "password": "",
            "url": "https://yugipedia.com/wiki/Hippo_Token",
            "passwordless": True,
        }
        for card_type in ("Token", "Monster Token", "Token Card"):
            with self.subTest(card_type=card_type):
                card_data, error = parse_card_page(html, {**base, "card_type": card_type})
                self.assertIsNone(error, msg=f"failed for card_type={card_type!r}")
                assert card_data is not None
                self.assertEqual(card_data["category"], "Token")
                self.assertEqual(card_data["type"], "Beast")


class TestAdapterPasswordless(unittest.TestCase):
    def test_passcode_none_source_url_preserved(self):
        entry = {
            "id": None,
            "source_url": "https://yugipedia.com/wiki/Obelisk_the_Tormentor",
            "name": "Obelisk the Tormentor",
            "typeline": ["Divine-Beast", "Effect"],
            "type": "Divine-Beast",
            "attribute": "DIVINE",
            "level": 10,
            "atk": 4000,
            "def": 4000,
            "card_sets": [{"set_code": "JUMP-EN037", "set_rarity_code": "UR"}],
        }
        api = yugipedia_card_to_api(entry)
        assert api is not None
        self.assertIsNone(api["id"])
        self.assertIsNone(api["passcode"])
        self.assertEqual(
            api["source_url"], "https://yugipedia.com/wiki/Obelisk_the_Tormentor"
        )
        self.assertIsNone(api["ygoprodeck_url"])

    def test_unidentifiable_entry_dropped(self):
        self.assertIsNone(yugipedia_card_to_api({"id": None, "name": "No Keys"}))


def _sqlite_engine(path: str):
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _pragma(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return eng


class TestImportUpsertPasswordless(unittest.TestCase):
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

    def _obelisk_entry(self, name="Obelisk the Tormentor"):
        return {
            "passcode": None,
            "source_url": "https://yugipedia.com/wiki/Obelisk_the_Tormentor",
            "name": name,
            "category": "Monster",
            "card_sets": [
                {
                    "set_code": "JUMP-EN037",
                    "set_name": "Shonen Jump promo",
                    "set_rarity": "Ultra Rare",
                    "set_rarity_code": "UR",
                }
            ],
        }

    def _real_entry(self):
        return {
            "passcode": 85087012,
            "source_url": "https://yugipedia.com/wiki/Card_Trooper",
            "name": "Card Trooper",
            "category": "Monster",
            "card_sets": [
                {"set_code": "RA03-EN172", "set_rarity": "Common", "set_rarity_code": "C"}
            ],
        }

    def test_passwordless_inserted_with_surrogate_id(self):
        cards, printings = import_cards_entries([self._obelisk_entry(), self._real_entry()])
        self.assertEqual(cards, 2)
        self.assertEqual(printings, 2)

        session = self.Session()
        try:
            obelisk = session.query(Card).filter(Card.name == "Obelisk the Tormentor").one()
            self.assertIsNone(obelisk.passcode)
            self.assertEqual(
                obelisk.source_url, "https://yugipedia.com/wiki/Obelisk_the_Tormentor"
            )
            self.assertIsNotNone(obelisk.id)

            trooper = session.query(Card).filter(Card.name == "Card Trooper").one()
            self.assertEqual(trooper.passcode, 85087012)
        finally:
            session.close()

    def test_reimport_matches_by_source_url_and_keeps_id(self):
        import_cards_entries([self._obelisk_entry()])
        session = self.Session()
        try:
            first_id = session.query(Card).filter(Card.name == "Obelisk the Tormentor").one().id
        finally:
            session.close()

        # Re-import with a changed name; must update in place, not create a new row.
        cards, _ = import_cards_entries([self._obelisk_entry(name="Obelisk (updated)")])
        self.assertEqual(cards, 1)

        session = self.Session()
        try:
            rows = session.query(Card).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].id, first_id)
            self.assertEqual(rows[0].name, "Obelisk (updated)")
        finally:
            session.close()

    def _case_for_k9_entry(self):
        return {
            "passcode": 80181649,
            "source_url": "https://yugipedia.com/wiki/%22A_Case_for_K9%22",
            "name": '"A Case for K9"',
            "category": "Spell",
            "card_sets": [
                {
                    "set_code": "DOOD-EN061",
                    "set_name": "Doom of Dimensions",
                    "set_rarity": "Common",
                    "set_rarity_code": "C",
                }
            ],
        }

    def test_legacy_id_row_reused_when_passcode_imported(self):
        """Pre-migration row (id=passcode, passcode NULL) must not spawn a surrogate duplicate."""
        session = self.Session()
        try:
            session.add(
                Card(
                    id=80181649,
                    passcode=None,
                    source_url="https://yugipedia.com/wiki/%22A_Case_for_K9%22",
                    name='"A Case for K9"',
                )
            )
            session.commit()
        finally:
            session.close()

        cards, _ = import_cards_entries([self._case_for_k9_entry()])
        self.assertEqual(cards, 1)

        session = self.Session()
        try:
            rows = session.query(Card).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].id, 80181649)
            self.assertEqual(rows[0].passcode, 80181649)
        finally:
            session.close()

    def test_surrogate_duplicate_pruned_when_legacy_row_exists(self):
        """Existing surrogate+legacy pair for the same passcode collapses on reimport."""
        session = self.Session()
        try:
            session.add(
                Card(
                    id=80181649,
                    passcode=None,
                    source_url="https://yugipedia.com/wiki/%22A_Case_for_K9%22",
                    name='"A Case for K9"',
                )
            )
            session.add(
                Card(
                    id=100006785,
                    passcode=80181649,
                    name='"A Case for K9"',
                )
            )
            session.commit()
        finally:
            session.close()

        cards, _ = import_cards_entries([self._case_for_k9_entry()])
        self.assertEqual(cards, 1)

        session = self.Session()
        try:
            rows = session.query(Card).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].id, 80181649)
            self.assertEqual(rows[0].passcode, 80181649)
            self.assertIsNone(session.get(Card, 100006785))
        finally:
            session.close()

    def test_seven_digit_legacy_id_row_reused_when_passcode_imported(self):
        """7-digit pre-migration rows (id=passcode) must not spawn surrogate duplicates."""
        session = self.Session()
        try:
            session.add(
                Card(
                    id=4731783,
                    passcode=None,
                    source_url="https://yugipedia.com/wiki/A_Bao_A_Qu,_the_Lightless_Shadow",
                    name="A Bao A Qu, the Lightless Shadow",
                )
            )
            session.commit()
        finally:
            session.close()

        cards, printings = import_cards_entries(
            [
                {
                    "passcode": 4731783,
                    "source_url": "https://yugipedia.com/wiki/A_Bao_A_Qu,_the_Lightless_Shadow",
                    "name": "A Bao A Qu, the Lightless Shadow",
                    "category": "Monster",
                    "card_sets": [
                        {
                            "set_code": "INFO-EN001",
                            "set_name": "The Infinite Forbidden",
                            "set_rarity": "Secret Rare",
                            "set_rarity_code": "ScR",
                        }
                    ],
                }
            ]
        )
        self.assertEqual(cards, 1)
        self.assertEqual(printings, 1)

        session = self.Session()
        try:
            rows = session.query(Card).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].id, 4731783)
            self.assertEqual(rows[0].passcode, 4731783)
        finally:
            session.close()

    def test_passcode_import_matches_prior_passwordless_row(self):
        import_cards_entries([self._obelisk_entry()])
        session = self.Session()
        try:
            first_id = session.query(Card).filter(Card.name == "Obelisk the Tormentor").one().id
        finally:
            session.close()

        cards, _ = import_cards_entries(
            [
                {
                    "passcode": 11037980,
                    "source_url": "https://yugipedia.com/wiki/Obelisk_the_Tormentor",
                    "name": "Obelisk the Tormentor",
                    "category": "Monster",
                    "card_sets": self._obelisk_entry()["card_sets"],
                }
            ]
        )
        self.assertEqual(cards, 1)

        session = self.Session()
        try:
            rows = session.query(Card).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].id, first_id)
            self.assertEqual(rows[0].passcode, 11037980)
        finally:
            session.close()


def _soup(html):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "html.parser")


if __name__ == "__main__":
    unittest.main()
