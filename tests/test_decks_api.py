"""Deck list, search, sort, preview cover, and update helpers."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.models import Base, Card, Deck, DeckCard, Format, User
from ygo_app.services import (
    apply_deck_save,
    clear_deck_preview_if_removed,
    compute_deck_preview_cards,
    deck_counts,
    list_decks_enriched,
    list_user_decks,
    reconcile_deck_cards,
    update_deck,
    _deck_card_entries_for_decks,
)


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


class TestDecksApi(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        user = User(email="decks@test.example", hashed_password="x")
        session.add(user)
        session.flush()
        self.user_id = user.id

        session.add(
            Format(
                code="advanced",
                name="Advanced",
                description="Advanced format",
                uses_banlist=True,
                uses_point_list=False,
                sort_order=0,
            )
        )

        cards = [
            Card(
                id=1001,
                name="Blue-Eyes White Dragon",
                image_url="https://example.com/blue-eyes.webp",
                image_url_small="https://example.com/blue-eyes-small.webp",
            ),
            Card(
                id=1002,
                name="Dark Magician",
                image_url="https://example.com/dm.webp",
                image_url_small="https://example.com/dm-small.webp",
            ),
            Card(
                id=1003,
                name="Pot of Greed",
                image_url="https://example.com/greed.webp",
                image_url_small="https://example.com/greed-small.webp",
            ),
        ]
        session.add_all(cards)

        now = datetime.utcnow()
        deck_a = Deck(
            user_id=self.user_id,
            name="Dragon Deck",
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(hours=1),
        )
        deck_b = Deck(
            user_id=self.user_id,
            name="Spell Control",
            created_at=now - timedelta(days=1),
            updated_at=now,
        )
        session.add_all([deck_a, deck_b])
        session.flush()
        self.deck_a_id = deck_a.id
        self.deck_b_id = deck_b.id

        session.add_all(
            [
                DeckCard(
                    deck_id=deck_a.id,
                    card_id=1001,
                    zone="main",
                    quantity=1,
                    sort_order=0,
                ),
                DeckCard(
                    deck_id=deck_a.id,
                    card_id=1001,
                    zone="main",
                    quantity=1,
                    sort_order=1,
                ),
                DeckCard(
                    deck_id=deck_a.id,
                    card_id=1001,
                    zone="main",
                    quantity=1,
                    sort_order=2,
                ),
                DeckCard(
                    deck_id=deck_a.id,
                    card_id=1002,
                    zone="main",
                    quantity=1,
                    sort_order=3,
                ),
                DeckCard(
                    deck_id=deck_b.id,
                    card_id=1003,
                    zone="main",
                    quantity=1,
                    sort_order=0,
                ),
                DeckCard(
                    deck_id=deck_b.id,
                    card_id=1003,
                    zone="main",
                    quantity=1,
                    sort_order=1,
                ),
            ]
        )
        session.commit()
        session.close()

    def tearDown(self):
        self.engine.dispose()
        os.unlink(self._tmp.name)

    def test_list_sort_by_name(self):
        session = self.Session()
        decks = list_user_decks(session, self.user_id, sort="name")
        self.assertEqual([d.name for d in decks], ["Dragon Deck", "Spell Control"])
        session.close()

    def test_list_sort_by_updated_at(self):
        session = self.Session()
        decks = list_user_decks(session, self.user_id, sort="updated_at")
        self.assertEqual(decks[0].name, "Spell Control")
        session.close()

    def test_search_by_deck_name(self):
        session = self.Session()
        decks = list_user_decks(session, self.user_id, q="dragon")
        self.assertEqual(len(decks), 1)
        self.assertEqual(decks[0].name, "Dragon Deck")
        session.close()

    def test_search_by_card_name(self):
        session = self.Session()
        decks = list_user_decks(session, self.user_id, q="Greed")
        self.assertEqual(len(decks), 1)
        self.assertEqual(decks[0].name, "Spell Control")
        session.close()

    def test_preview_cards_cover_first(self):
        session = self.Session()
        deck = session.get(Deck, self.deck_a_id)
        deck.preview_card_id = 1002
        session.commit()
        entries = _deck_card_entries_for_decks(session, [self.deck_a_id])[self.deck_a_id]
        previews = compute_deck_preview_cards(deck.preview_card_id, entries)
        self.assertEqual([p["card_id"] for p in previews], [1002, 1001])
        session.close()

    def test_list_enriched_card_count(self):
        session = self.Session()
        rows = list_decks_enriched(session, self.user_id, sort="name")
        dragon = next(r for r in rows if r["name"] == "Dragon Deck")
        self.assertEqual(dragon["card_count"], 4)
        self.assertEqual(len(dragon["preview_cards"]), 2)
        session.close()

    def test_update_preview_requires_card_in_deck(self):
        session = self.Session()
        deck = session.get(Deck, self.deck_b_id)
        with self.assertRaises(ValueError):
            update_deck(session, deck, {"preview_card_id": 1001})
        session.close()

    def test_update_preview_card(self):
        session = self.Session()
        deck = session.get(Deck, self.deck_b_id)
        update_deck(session, deck, {"preview_card_id": 1003})
        self.assertEqual(deck.preview_card_id, 1003)
        session.close()

    def test_clear_preview_when_card_removed(self):
        session = self.Session()
        deck = session.get(Deck, self.deck_b_id)
        deck.preview_card_id = 1003
        session.commit()
        row = session.execute(
            select(DeckCard).where(
                DeckCard.deck_id == self.deck_b_id,
                DeckCard.card_id == 1003,
            )
        ).scalars().all()
        for deck_card in row:
            session.delete(deck_card)
        clear_deck_preview_if_removed(session, self.deck_b_id, 1003)
        session.commit()
        deck = session.get(Deck, self.deck_b_id)
        self.assertIsNone(deck.preview_card_id)
        session.close()

    def test_clear_preview_keeps_when_card_remains_in_other_zone(self):
        session = self.Session()
        deck = session.get(Deck, self.deck_a_id)
        deck.preview_card_id = 1001
        session.add(
            DeckCard(
                deck_id=self.deck_a_id,
                card_id=1001,
                zone="side",
                quantity=1,
                sort_order=0,
            )
        )
        session.commit()
        main_rows = session.execute(
            select(DeckCard).where(
                DeckCard.deck_id == self.deck_a_id,
                DeckCard.card_id == 1001,
                DeckCard.zone == "main",
            )
        ).scalars().all()
        for deck_card in main_rows:
            session.delete(deck_card)
        clear_deck_preview_if_removed(session, self.deck_a_id, 1001)
        session.commit()
        deck = session.get(Deck, self.deck_a_id)
        self.assertEqual(deck.preview_card_id, 1001)
        session.close()

    def test_deck_counts(self):
        session = self.Session()
        counts = deck_counts(session, self.deck_a_id)
        self.assertEqual(counts["main"], 4)
        session.close()

    def test_apply_deck_save_reconciles_cards(self):
        session = self.Session()
        deck = session.get(Deck, self.deck_a_id)
        apply_deck_save(
            session,
            deck,
            {
                "name": "Dragon Deck",
                "description": None,
                "format_code": "advanced",
                "banlist_revision_id": None,
                "genesys_point_list_id": None,
                "preview_card_id": 1001,
                "cards": [
                    {"card_id": 1001, "zone": "main", "quantity": 2},
                    {"card_id": 1003, "zone": "side", "quantity": 1},
                ],
            },
        )
        session.commit()
        rows = session.execute(
            select(DeckCard).where(DeckCard.deck_id == self.deck_a_id)
        ).scalars().all()
        counts: dict[tuple[int, str], int] = {}
        for row in rows:
            key = (row.card_id, row.zone)
            counts[key] = counts.get(key, 0) + row.quantity
        self.assertEqual(counts, {(1001, "main"): 2, (1003, "side"): 1})
        self.assertTrue(all(row.quantity == 1 for row in rows))
        self.assertEqual(deck.preview_card_id, 1001)
        session.close()

    def test_reconcile_preserves_card_order(self):
        session = self.Session()
        deck = session.get(Deck, self.deck_a_id)
        apply_deck_save(
            session,
            deck,
            {
                "name": deck.name,
                "description": deck.description,
                "format_code": deck.format_code,
                "banlist_revision_id": deck.banlist_revision_id,
                "genesys_point_list_id": deck.genesys_point_list_id,
                "preview_card_id": deck.preview_card_id,
                "cards": [
                    {"card_id": 1002, "zone": "main", "quantity": 1},
                    {"card_id": 1001, "zone": "main", "quantity": 1},
                    {"card_id": 1001, "zone": "main", "quantity": 1},
                ],
            },
        )
        session.commit()
        rows = session.execute(
            select(DeckCard)
            .where(DeckCard.deck_id == self.deck_a_id, DeckCard.zone == "main")
            .order_by(DeckCard.sort_order.asc())
        ).scalars().all()
        self.assertEqual([row.card_id for row in rows], [1002, 1001, 1001])
        self.assertEqual([row.sort_order for row in rows], [0, 1, 2])
        session.close()

    def test_reconcile_interleaved_duplicates(self):
        session = self.Session()
        deck = session.get(Deck, self.deck_a_id)
        apply_deck_save(
            session,
            deck,
            {
                "name": deck.name,
                "description": deck.description,
                "format_code": deck.format_code,
                "banlist_revision_id": deck.banlist_revision_id,
                "genesys_point_list_id": deck.genesys_point_list_id,
                "preview_card_id": deck.preview_card_id,
                "cards": [
                    {"card_id": 1001, "zone": "main", "quantity": 1},
                    {"card_id": 1002, "zone": "main", "quantity": 1},
                    {"card_id": 1001, "zone": "main", "quantity": 1},
                ],
            },
        )
        session.commit()
        rows = session.execute(
            select(DeckCard)
            .where(DeckCard.deck_id == self.deck_a_id, DeckCard.zone == "main")
            .order_by(DeckCard.sort_order.asc())
        ).scalars().all()
        self.assertEqual([row.card_id for row in rows], [1001, 1002, 1001])
        session.close()

    def test_reconcile_cross_zone_order(self):
        session = self.Session()
        deck = session.get(Deck, self.deck_a_id)
        apply_deck_save(
            session,
            deck,
            {
                "name": deck.name,
                "description": deck.description,
                "format_code": deck.format_code,
                "banlist_revision_id": deck.banlist_revision_id,
                "genesys_point_list_id": deck.genesys_point_list_id,
                "preview_card_id": deck.preview_card_id,
                "cards": [
                    {"card_id": 1001, "zone": "main", "quantity": 1},
                    {"card_id": 1002, "zone": "side", "quantity": 1},
                    {"card_id": 1001, "zone": "main", "quantity": 1},
                ],
            },
        )
        session.commit()
        main_rows = session.execute(
            select(DeckCard)
            .where(DeckCard.deck_id == self.deck_a_id, DeckCard.zone == "main")
            .order_by(DeckCard.sort_order.asc())
        ).scalars().all()
        side_rows = session.execute(
            select(DeckCard)
            .where(DeckCard.deck_id == self.deck_a_id, DeckCard.zone == "side")
            .order_by(DeckCard.sort_order.asc())
        ).scalars().all()
        self.assertEqual([row.card_id for row in main_rows], [1001, 1001])
        self.assertEqual([row.card_id for row in side_rows], [1002])
        counts = deck_counts(session, self.deck_a_id)
        self.assertEqual(counts["main"], 2)
        self.assertEqual(counts["side"], 1)
        session.close()

    def test_apply_deck_save_clears_preview_when_cover_removed(self):
        session = self.Session()
        deck = session.get(Deck, self.deck_a_id)
        deck.preview_card_id = 1002
        session.commit()
        apply_deck_save(
            session,
            deck,
            {
                "name": deck.name,
                "description": deck.description,
                "format_code": deck.format_code,
                "banlist_revision_id": deck.banlist_revision_id,
                "genesys_point_list_id": deck.genesys_point_list_id,
                "preview_card_id": None,
                "cards": [{"card_id": 1001, "zone": "main", "quantity": 1}],
            },
        )
        session.commit()
        self.assertIsNone(deck.preview_card_id)
        session.close()


if __name__ == "__main__":
    unittest.main()
