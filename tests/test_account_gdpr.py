"""Account deletion and personal data export (GDPR)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.api.main import app
from ygo_app.auth import create_access_token, hash_password
from ygo_app.database import get_db
from ygo_app.models import (
    AuthRateLimit,
    Base,
    Card,
    CollectionItem,
    Deck,
    DeckCard,
    Format,
    OAuthIdentity,
    PendingRegistration,
    SearchPreset,
    User,
    UserFavorite,
)
from ygo_app.trade_share import ensure_user_trade_slug

TEST_PASSWORD = "Password1!"


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


class TestAccountGdpr(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        session.add(
            Format(code="advanced", name="Advanced", description="Adv", sort_order=1)
        )
        self.user = User(
            email="owner@test.example",
            hashed_password=hash_password(TEST_PASSWORD),
            email_verified_at=datetime.utcnow(),
        )
        self.other = User(
            email="other@test.example",
            hashed_password=hash_password(TEST_PASSWORD),
            email_verified_at=datetime.utcnow(),
        )
        session.add_all([self.user, self.other])
        session.flush()
        ensure_user_trade_slug(session, self.user)
        ensure_user_trade_slug(session, self.other)

        card = Card(
            id=89631139,
            passcode=89631139,
            name="Blue-Eyes White Dragon",
            category="Monster",
            types='["Dragon", "Normal"]',
        )
        session.add(card)
        session.flush()

        session.add(
            CollectionItem(
                user_id=self.user.id,
                set_code="LOB-001",
                rarity_code="(UR)",
                card_name=card.name,
                quantity=2,
            )
        )
        deck = Deck(
            user_id=self.user.id,
            name="BEWD Deck",
            format_code="advanced",
            description="Test deck",
        )
        session.add(deck)
        session.flush()
        session.add(
            DeckCard(deck_id=deck.id, card_id=card.id, zone="main", quantity=3, sort_order=0)
        )
        session.add(UserFavorite(user_id=self.user.id, card_id=card.id))
        session.add(
            SearchPreset(
                user_id=self.user.id,
                name="Dragons",
                params=json.dumps({"q": "dragon"}),
            )
        )
        session.add(
            AuthRateLimit(
                key=f"login:email:{self.user.email}",
                count=2,
                window_start=datetime.utcnow(),
            )
        )
        session.add(
            AuthRateLimit(
                key="login:ip:127.0.0.1",
                count=1,
                window_start=datetime.utcnow(),
            )
        )
        session.add(
            CollectionItem(
                user_id=self.other.id,
                set_code="SDK-001",
                rarity_code="(UR)",
                card_name="Other card",
                quantity=1,
            )
        )
        session.commit()
        self.user_id = self.user.id
        self.other_id = self.other.id
        self.card_id = card.id
        session.close()

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.auth_headers = {
            "Authorization": f"Bearer {create_access_token(self.user_id)}"
        }
        self.other_headers = {
            "Authorization": f"Bearer {create_access_token(self.other_id)}"
        }

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_me_includes_has_password(self):
        res = self.client.get("/api/auth/me", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["has_password"])
        self.assertEqual(body["email"], "owner@test.example")

    def test_data_export_includes_own_data_only(self):
        res = self.client.get("/api/auth/data-export", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn("attachment", res.headers.get("content-disposition", ""))
        payload = res.json()
        self.assertEqual(payload["profile"]["email"], "owner@test.example")
        self.assertEqual(len(payload["collection"]), 1)
        self.assertEqual(payload["collection"][0]["set_code"], "LOB-001")
        self.assertEqual(len(payload["decks"]), 1)
        self.assertEqual(payload["decks"][0]["name"], "BEWD Deck")
        self.assertEqual(payload["decks"][0]["cards"][0]["card_id"], self.card_id)
        self.assertEqual(len(payload["favorites"]), 1)
        self.assertEqual(len(payload["search_presets"]), 1)
        self.assertEqual(payload["search_presets"][0]["params"]["q"], "dragon")
        dumped = json.dumps(payload)
        self.assertNotIn("hashed_password", dumped)
        self.assertNotIn("Other card", dumped)

    def test_data_export_requires_auth(self):
        res = self.client.get("/api/auth/data-export")
        self.assertEqual(res.status_code, 401)

    def test_delete_account_wrong_password(self):
        res = self.client.request(
            "DELETE",
            "/api/auth/account",
            headers=self.auth_headers,
            json={"password": "WrongPass1!"},
        )
        self.assertEqual(res.status_code, 401)
        session = self.Session()
        self.assertIsNotNone(session.get(User, self.user_id))
        session.close()

    def test_delete_account_removes_user_and_cascades(self):
        res = self.client.request(
            "DELETE",
            "/api/auth/account",
            headers=self.auth_headers,
            json={"password": TEST_PASSWORD},
        )
        self.assertEqual(res.status_code, 204, res.text)

        session = self.Session()
        self.assertIsNone(session.get(User, self.user_id))
        self.assertEqual(
            session.scalar(
                select(CollectionItem).where(CollectionItem.user_id == self.user_id)
            ),
            None,
        )
        self.assertEqual(
            session.scalar(select(Deck).where(Deck.user_id == self.user_id)),
            None,
        )
        self.assertIsNone(
            session.get(AuthRateLimit, f"login:email:owner@test.example")
        )
        self.assertIsNotNone(session.get(AuthRateLimit, "login:ip:127.0.0.1"))
        other_item = session.scalar(
            select(CollectionItem).where(CollectionItem.user_id == self.other_id)
        )
        self.assertIsNotNone(other_item)
        session.close()

    def test_delete_oauth_only_requires_email_confirm(self):
        session = self.Session()
        oauth_user = User(
            email="oauth@test.example",
            hashed_password=None,
            email_verified_at=datetime.utcnow(),
        )
        session.add(oauth_user)
        session.flush()
        ensure_user_trade_slug(session, oauth_user)
        session.add(
            OAuthIdentity(
                user_id=oauth_user.id,
                provider="google",
                provider_user_id="g-1",
                provider_email="oauth@test.example",
            )
        )
        session.add(
            PendingRegistration(
                email="oauth@test.example",
                hashed_password=hash_password(TEST_PASSWORD),
                otp_hash="abc",
                otp_expires_at=datetime.utcnow(),
            )
        )
        session.commit()
        oauth_id = oauth_user.id
        session.close()

        headers = {"Authorization": f"Bearer {create_access_token(oauth_id)}"}
        bad = self.client.request(
            "DELETE",
            "/api/auth/account",
            headers=headers,
            json={"confirm_email": "wrong@test.example"},
        )
        self.assertEqual(bad.status_code, 400)

        me = self.client.get("/api/auth/me", headers=headers)
        self.assertFalse(me.json()["has_password"])

        ok = self.client.request(
            "DELETE",
            "/api/auth/account",
            headers=headers,
            json={"confirm_email": "oauth@test.example"},
        )
        self.assertEqual(ok.status_code, 204, ok.text)

        session = self.Session()
        self.assertIsNone(session.get(User, oauth_id))
        self.assertEqual(
            session.scalar(
                select(PendingRegistration).where(
                    PendingRegistration.email == "oauth@test.example"
                )
            ),
            None,
        )
        session.close()


if __name__ == "__main__":
    unittest.main()
