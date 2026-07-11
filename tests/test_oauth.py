"""OAuth 2.0 social sign-in."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.api.main import app
from ygo_app.auth import hash_password
from ygo_app.database import get_db
from ygo_app.models import Base, OAuthIdentity, User
from ygo_app.oauth import (
    create_oauth_exchange_token,
    create_oauth_state,
    verify_oauth_exchange_token,
    verify_oauth_state,
)

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


class TestOAuth(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        self.config_patcher = patch.multiple(
            "ygo_app.oauth",
            GOOGLE_CLIENT_ID="google-id",
            GOOGLE_CLIENT_SECRET="google-secret",
            DISCORD_CLIENT_ID=None,
            DISCORD_CLIENT_SECRET=None,
            GITHUB_CLIENT_ID="github-id",
            GITHUB_CLIENT_SECRET="github-secret",
            MICROSOFT_CLIENT_ID=None,
            MICROSOFT_CLIENT_SECRET=None,
            OAUTH_REDIRECT_BASE_URL="http://testserver",
        )
        self.config_patcher.start()

    def tearDown(self):
        self.config_patcher.stop()
        app.dependency_overrides.clear()
        self.client.close()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def _create_user(
        self,
        email: str = "user@test.example",
        *,
        password: str | None = TEST_PASSWORD,
        verified: bool = True,
    ) -> User:
        with self.Session() as db:
            user = User(
                email=email,
                hashed_password=hash_password(password) if password else None,
                email_verified_at=datetime.utcnow() if verified else None,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user

    def test_auth_config_lists_configured_providers(self):
        res = self.client.get("/api/auth/config")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        ids = {p["id"] for p in data["oauth_providers"]}
        self.assertIn("google", ids)
        self.assertIn("github", ids)
        self.assertNotIn("discord", ids)
        self.assertNotIn("microsoft", ids)

    def test_oauth_start_redirects_to_provider(self):
        res = self.client.get("/api/auth/oauth/google/start", follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        location = res.headers["location"]
        self.assertIn("accounts.google.com", location)
        self.assertIn("client_id=google-id", location)
        self.assertIn("state=", location)

    def test_oauth_start_unknown_provider(self):
        res = self.client.get("/api/auth/oauth/discord/start", follow_redirects=False)
        self.assertEqual(res.status_code, 404)

    @patch("ygo_app.api.routes.auth.exchange_code_and_fetch_profile")
    def test_oauth_callback_creates_user_and_redirects(self, mock_exchange):
        mock_exchange.return_value = {
            "provider_user_id": "google-sub-1",
            "email": "oauth-new@test.example",
            "email_verified": True,
        }
        state = create_oauth_state("google")
        res = self.client.get(
            f"/api/auth/oauth/google/callback?code=abc&state={state}",
            follow_redirects=False,
        )
        self.assertEqual(res.status_code, 302)
        self.assertIn("oauth_exchange=", res.headers["location"])

        with self.Session() as db:
            user = db.execute(
                select(User).where(User.email == "oauth-new@test.example")
            ).scalar_one()
            self.assertIsNone(user.hashed_password)
            self.assertIsNotNone(user.email_verified_at)
            identity = db.execute(
                select(OAuthIdentity).where(
                    OAuthIdentity.provider == "google",
                    OAuthIdentity.provider_user_id == "google-sub-1",
                )
            ).scalar_one()
            self.assertEqual(identity.user_id, user.id)

    @patch("ygo_app.api.routes.auth.exchange_code_and_fetch_profile")
    def test_oauth_callback_links_existing_verified_user(self, mock_exchange):
        existing = self._create_user("linked@test.example")
        mock_exchange.return_value = {
            "provider_user_id": "google-sub-2",
            "email": "linked@test.example",
            "email_verified": True,
        }
        state = create_oauth_state("google")
        res = self.client.get(
            f"/api/auth/oauth/google/callback?code=abc&state={state}",
            follow_redirects=False,
        )
        self.assertEqual(res.status_code, 302)

        with self.Session() as db:
            users = db.execute(select(User).where(User.email == "linked@test.example")).scalars().all()
            self.assertEqual(len(users), 1)
            identity = db.execute(
                select(OAuthIdentity).where(OAuthIdentity.user_id == existing.id)
            ).scalar_one()
            self.assertEqual(identity.provider, "google")

    def test_oauth_callback_rejects_invalid_state(self):
        res = self.client.get(
            "/api/auth/oauth/google/callback?code=abc&state=bad-state",
            follow_redirects=False,
        )
        self.assertIn(res.status_code, (302, 307))
        self.assertIn("oauth_error=", res.headers["location"])

    def test_oauth_complete_returns_jwt(self):
        user = self._create_user("complete@test.example")
        exchange = create_oauth_exchange_token(user.id)
        res = self.client.post(
            "/api/auth/oauth/complete",
            json={"exchange_token": exchange},
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("access_token", res.json())

    def test_oauth_complete_rejects_invalid_exchange_token(self):
        res = self.client.post(
            "/api/auth/oauth/complete",
            json={"exchange_token": "not-a-valid-token"},
        )
        self.assertEqual(res.status_code, 400)

    def test_login_blocked_for_oauth_only_user(self):
        self._create_user("oauth-only@test.example", password=None)
        res = self.client.post(
            "/api/auth/login",
            json={"email": "oauth-only@test.example", "password": TEST_PASSWORD},
        )
        self.assertEqual(res.status_code, 401)
        self.assertIn("social sign-in", res.json()["detail"].lower())

    def test_register_blocked_for_oauth_only_email(self):
        self._create_user("oauth-only@test.example", password=None)
        res = self.client.post(
            "/api/auth/register",
            json={"email": "oauth-only@test.example", "password": TEST_PASSWORD},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("social sign-in", res.json()["detail"].lower())

    def test_state_and_exchange_token_round_trip(self):
        state = create_oauth_state("google")
        verify_oauth_state(state, "google")
        user = self._create_user("token@test.example")
        exchange = create_oauth_exchange_token(user.id)
        self.assertEqual(verify_oauth_exchange_token(exchange), user.id)

    def test_oauth_start_rate_limited(self):
        for _ in range(20):
            res = self.client.get("/api/auth/oauth/google/start", follow_redirects=False)
            self.assertEqual(res.status_code, 302)
        res = self.client.get("/api/auth/oauth/google/start", follow_redirects=False)
        self.assertEqual(res.status_code, 429)


if __name__ == "__main__":
    unittest.main()
