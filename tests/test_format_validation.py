"""Tests for deck format validation."""

import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ygo_app.database import Base
from ygo_app.formats.validate import validate_deck
from ygo_app.models import Card, Deck, DeckCard, Format, User


class FormatValidationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        session = self.Session()
        session.add(
            Format(
                code="advanced",
                name="Advanced TCG",
                description="test",
                uses_banlist=True,
                uses_point_list=False,
                sort_order=1,
            )
        )
        session.add(User(id=1, email="test@example.com", hashed_password="x"))
        session.add(
            Card(
                id=89631139,
                name="Blue-Eyes White Dragon",
                type="Normal Monster",
                category="Monster",
                mechanic="Normal",
            )
        )
        session.commit()
        session.close()

    def test_main_deck_too_small(self):
        session = self.Session()
        deck = Deck(
            user_id=1,
            name="Test",
            format_code="advanced",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(deck)
        session.flush()
        session.add(
            DeckCard(
                deck_id=deck.id,
                card_id=89631139,
                zone="main",
                quantity=1,
            )
        )
        session.commit()
        result = validate_deck(session, deck)
        self.assertTrue(any(issue.code == "main_too_small" for issue in result.errors))
        session.close()


if __name__ == "__main__":
    unittest.main()
