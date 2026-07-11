"""Public trade subsite API and owner trade settings."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.api.main import app
from ygo_app.auth import create_access_token
from ygo_app.database import get_db
from ygo_app.models import Base, Card, CollectionItem, Printing, User
from ygo_app.trade_share import generate_trade_share_slug


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


class TestPublicTrade(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = _sqlite_engine(self._tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        session = self.Session()
        self.owner = User(
            email="owner@test.example",
            hashed_password="x",
            email_verified_at=datetime.utcnow(),
            trade_share_slug="owner-trade-list",
            trade_display_name="Owner Shop",
        )
        self.other = User(
            email="other@test.example",
            hashed_password="x",
            email_verified_at=datetime.utcnow(),
            trade_share_slug="other-trade-list",
        )
        session.add_all([self.owner, self.other])
        session.flush()

        card = Card(id=89631139, name="Blue-Eyes White Dragon")
        session.add(card)
        session.add(
            Printing(
                card_id=card.id,
                set_code="LOB-001",
                set_rarity_code="(UR)",
                set_rarity="Ultra Rare",
            )
        )
        session.flush()

        self.trade_item = CollectionItem(
            user_id=self.owner.id,
            set_code="LOB-001",
            rarity_code="(UR)",
            card_name=card.name,
            quantity=2,
            trade_quantity=2,
            sell_price=12.5,
            condition="NearMint",
        )
        self.private_item = CollectionItem(
            user_id=self.owner.id,
            set_code="LOB-001",
            rarity_code="(UR)",
            card_name=card.name,
            quantity=1,
            trade_quantity=0,
        )
        self.foreign_item = CollectionItem(
            user_id=self.other.id,
            set_code="LOB-001",
            rarity_code="(UR)",
            card_name=card.name,
            quantity=1,
            trade_quantity=1,
        )
        session.add_all([self.trade_item, self.private_item, self.foreign_item])
        session.commit()
        self.trade_item_id = self.trade_item.id
        self.foreign_item_id = self.foreign_item.id

        self.owner_token = create_access_token(self.owner.id)
        self.other_token = create_access_token(self.other.id)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.engine.dispose()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_public_trade_list_only_includes_trade_quantity(self):
        response = self.client.get("/api/public/trade/owner-trade-list")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["seller"]["display_name"], "Owner Shop")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["item_id"], self.trade_item_id)
        self.assertEqual(item["trade_quantity"], 2)
        self.assertNotIn("email", payload)
        self.assertNotIn("notes", item)

    def test_invalid_slug_returns_404(self):
        response = self.client.get("/api/public/trade/does-not-exist")
        self.assertEqual(response.status_code, 404)

    def test_public_trade_filters(self):
        response = self.client.get("/api/public/trade/owner-trade-list/filters")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["set_codes"], ["LOB-001"])
        self.assertEqual(payload["conditions"], ["NearMint"])

    @patch("ygo_app.api.routes.public_trade.send_trade_order_request")
    def test_order_request_happy_path(self, send_mock):
        response = self.client.post(
            "/api/public/trade/owner-trade-list/order-request",
            json={
                "lines": [{"item_id": self.trade_item_id, "quantity": 1, "comment": "Hi"}],
                "name": "Buyer",
                "email": "buyer@test.example",
                "gdpr_consent": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Order request sent.")
        send_mock.assert_called_once()

    @patch("ygo_app.api.routes.public_trade.send_trade_order_request")
    def test_order_request_rejects_excess_quantity(self, _send_mock):
        response = self.client.post(
            "/api/public/trade/owner-trade-list/order-request",
            json={
                "lines": [{"item_id": self.trade_item_id, "quantity": 99}],
                "gdpr_consent": True,
            },
        )
        self.assertEqual(response.status_code, 400)

    @patch("ygo_app.api.routes.public_trade.send_trade_order_request")
    def test_order_request_rejects_foreign_item(self, _send_mock):
        response = self.client.post(
            "/api/public/trade/owner-trade-list/order-request",
            json={
                "lines": [{"item_id": self.foreign_item_id, "quantity": 1}],
                "gdpr_consent": True,
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_order_request_requires_gdpr_consent(self):
        response = self.client.post(
            "/api/public/trade/owner-trade-list/order-request",
            json={
                "lines": [{"item_id": self.trade_item_id, "quantity": 1}],
                "gdpr_consent": False,
            },
        )
        self.assertEqual(response.status_code, 422)

    @patch("ygo_app.api.routes.public_trade.verify_turnstile_token", return_value=False)
    @patch("ygo_app.api.routes.public_trade.turnstile_required", return_value=True)
    def test_order_request_turnstile_failure(self, _required, _verify):
        response = self.client.post(
            "/api/public/trade/owner-trade-list/order-request",
            json={
                "lines": [{"item_id": self.trade_item_id, "quantity": 1}],
                "gdpr_consent": True,
                "turnstile_token": "bad",
            },
        )
        self.assertEqual(response.status_code, 400)

    @patch("ygo_app.api.routes.public_trade.send_trade_order_request")
    def test_order_request_rate_limit(self, _send_mock):
        body = {
            "lines": [{"item_id": self.trade_item_id, "quantity": 1}],
            "gdpr_consent": True,
        }
        for _ in range(5):
            response = self.client.post(
                "/api/public/trade/owner-trade-list/order-request",
                json=body,
            )
            self.assertEqual(response.status_code, 200)
        response = self.client.post(
            "/api/public/trade/owner-trade-list/order-request",
            json=body,
        )
        self.assertEqual(response.status_code, 429)

    def test_trade_settings_get_and_patch(self):
        response = self.client.get(
            "/api/collection/trade-settings",
            headers={"Authorization": f"Bearer {self.owner_token}"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["slug"], "owner-trade-list")
        self.assertEqual(payload["trade_url"], "/trade/owner-trade-list")

        conflict = self.client.patch(
            "/api/collection/trade-settings",
            headers={"Authorization": f"Bearer {self.owner_token}"},
            json={"slug": "other-trade-list"},
        )
        self.assertEqual(conflict.status_code, 409)

        updated = self.client.patch(
            "/api/collection/trade-settings",
            headers={"Authorization": f"Bearer {self.other_token}"},
            json={"slug": "renamed-shop", "display_name": "Renamed"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["slug"], "renamed-shop")
        self.assertEqual(updated.json()["display_name"], "Renamed")

    def test_trade_page_and_legal_routes(self):
        trade = self.client.get("/trade/owner-trade-list")
        self.assertEqual(trade.status_code, 200)
        self.assertIn("text/html", trade.headers.get("content-type", ""))

        privacy = self.client.get("/legal/privacy")
        self.assertEqual(privacy.status_code, 200)

        missing = self.client.get("/legal/terms")
        self.assertEqual(missing.status_code, 404)

    def test_generate_trade_share_slug_is_url_safe(self):
        slug = generate_trade_share_slug()
        self.assertGreaterEqual(len(slug), 16)

    @patch("ygo_app.api.routes.public_trade.get_eur_huf_rate")
    def test_public_config_includes_live_rate(self, rate_mock):
        from ygo_app.currency import EurHufRate

        rate_mock.return_value = EurHufRate(rate=392.15, source="live", as_of="2026-07-10")
        response = self.client.get("/api/public/config")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["base_currency"], "EUR")
        self.assertEqual(payload["eur_huf_rate"], 392.15)
        self.assertEqual(payload["eur_huf_rate_source"], "live")
        self.assertEqual(payload["eur_huf_rate_as_of"], "2026-07-10")

    @patch("ygo_app.api.routes.public_trade.get_eur_huf_rate")
    def test_public_config_includes_fallback_rate(self, rate_mock):
        from ygo_app.currency import EurHufRate

        rate_mock.return_value = EurHufRate(rate=400.0, source="fallback", as_of=None)
        response = self.client.get("/api/public/config")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["eur_huf_rate"], 400.0)
        self.assertEqual(payload["eur_huf_rate_source"], "fallback")
        self.assertIsNone(payload["eur_huf_rate_as_of"])


if __name__ == "__main__":
    unittest.main()
