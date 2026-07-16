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
from ygo_app.models import Base, Card, CollectionItem, Printing, PrintingMarketPrice, User
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

        card = Card(
            id=89631139,
            passcode=89631139,
            name="Blue-Eyes White Dragon",
            type="Normal Monster",
            category="Monster",
            types='["Dragon", "Normal"]',
            attribute="LIGHT",
            level=8,
            atk=3000,
            def_=2500,
            desc="This legendary dragon is a powerful engine of destruction.",
            image_url="https://example.com/bevd.jpg",
            image_url_small="https://example.com/bevd-small.jpg",
        )
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
            edition="1st Edition",
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
        self.assertEqual(item["rarity_code"], "(UR)")
        self.assertEqual(item["rarity_display"], "UR")
        self.assertEqual(item["rarity_name"], "Ultra Rare")
        self.assertEqual(item["edition"], "1st Edition")
        self.assertEqual(item["condition"], "NearMint")
        self.assertEqual(item["image_url_small"], "https://example.com/bevd-small.jpg")
        card = item["card"]
        self.assertIsNotNone(card)
        self.assertEqual(card["id"], 89631139)
        self.assertEqual(card["passcode"], 89631139)
        self.assertEqual(card["name"], "Blue-Eyes White Dragon")
        self.assertEqual(card["type"], "Normal Monster")
        self.assertEqual(card["category"], "Monster")
        self.assertEqual(card["types"], ["Dragon", "Normal"])
        self.assertEqual(card["attribute"], "LIGHT")
        self.assertEqual(card["level"], 8)
        self.assertEqual(card["atk"], 3000)
        self.assertEqual(card["def"], 2500)
        self.assertEqual(
            card["desc"],
            "This legendary dragon is a powerful engine of destruction.",
        )
        self.assertEqual(card["image_url"], "https://example.com/bevd.jpg")
        self.assertEqual(card["image_url_small"], "https://example.com/bevd-small.jpg")
        self.assertNotIn("email", payload)
        self.assertNotIn("notes", item)

    def test_public_trade_falls_back_to_market_trend_when_sell_price_unset(self):
        session = self.Session()
        card = Card(id=48206762, name="Fallen of Albaz")
        session.add(card)
        session.add(
            Printing(
                card_id=card.id,
                set_code="CH01-EN001",
                set_rarity_code="(UR)",
                set_rarity="Ultra Rare",
            )
        )
        session.flush()
        trade_item = CollectionItem(
            user_id=self.owner.id,
            set_code="CH01-EN001",
            rarity_code="(UR)",
            card_name=card.name,
            quantity=1,
            trade_quantity=1,
            condition="NearMint",
        )
        session.add(trade_item)
        session.add(
            PrintingMarketPrice(
                set_code="CH01-EN001",
                rarity_code="(UR)",
                trend_price=0.2,
                currency="EUR",
                valid_from=datetime.utcnow(),
                is_current=True,
            )
        )
        session.commit()
        trade_item_id = trade_item.id
        session.close()

        response = self.client.get("/api/public/trade/owner-trade-list")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        row = next(item for item in payload["items"] if item["item_id"] == trade_item_id)
        self.assertEqual(row["sell_price"], 0.2)

    def test_public_trade_sort_by_sell_price_uses_resolved_list_price(self):
        """Sort by sell_price must use COALESCE(override, market trend), not raw NULLs."""
        session = self.Session()
        expensive_trend = Card(id=48206762, name="Fallen of Albaz")
        cheap_trend = Card(id=68468403, name="Incredible Ecclesia")
        override_card = Card(id=91070115, name="Aluber the Jester")
        session.add_all([expensive_trend, cheap_trend, override_card])
        session.flush()

        # Insert higher-trend card first so id order is opposite of price order.
        high_item = CollectionItem(
            user_id=self.owner.id,
            set_code="CH01-EN001",
            rarity_code="(UR)",
            card_name=expensive_trend.name,
            quantity=1,
            trade_quantity=1,
            condition="NearMint",
        )
        low_item = CollectionItem(
            user_id=self.owner.id,
            set_code="CH01-EN002",
            rarity_code="(UR)",
            card_name=cheap_trend.name,
            quantity=1,
            trade_quantity=1,
            condition="NearMint",
        )
        override_item = CollectionItem(
            user_id=self.owner.id,
            set_code="CH01-EN003",
            rarity_code="(SR)",
            card_name=override_card.name,
            quantity=1,
            trade_quantity=1,
            sell_price=0.05,
            condition="NearMint",
        )
        session.add_all([high_item, low_item, override_item])
        session.add_all(
            [
                PrintingMarketPrice(
                    set_code="CH01-EN001",
                    rarity_code="(UR)",
                    trend_price=0.4,
                    currency="EUR",
                    valid_from=datetime.utcnow(),
                    is_current=True,
                ),
                PrintingMarketPrice(
                    set_code="CH01-EN002",
                    rarity_code="(UR)",
                    trend_price=0.1,
                    currency="EUR",
                    valid_from=datetime.utcnow(),
                    is_current=True,
                ),
                PrintingMarketPrice(
                    set_code="CH01-EN003",
                    rarity_code="(SR)",
                    trend_price=9.0,
                    currency="EUR",
                    valid_from=datetime.utcnow(),
                    is_current=True,
                ),
            ]
        )
        session.commit()
        high_id = high_item.id
        low_id = low_item.id
        override_id = override_item.id
        session.close()

        # Existing setUp row is LOB-001 at 12.5; resolved order asc:
        # override 0.05, trend 0.1, trend 0.4, LOB 12.5
        asc = self.client.get(
            "/api/public/trade/owner-trade-list",
            params={"sort": "sell_price", "sort_dir": "asc"},
        )
        self.assertEqual(asc.status_code, 200)
        asc_ids = [item["item_id"] for item in asc.json()["items"]]
        self.assertEqual(
            asc_ids,
            [override_id, low_id, high_id, self.trade_item_id],
        )
        asc_prices = [item["sell_price"] for item in asc.json()["items"]]
        self.assertEqual(asc_prices, [0.05, 0.1, 0.4, 12.5])

        desc = self.client.get(
            "/api/public/trade/owner-trade-list",
            params={"sort": "sell_price", "sort_dir": "desc"},
        )
        self.assertEqual(desc.status_code, 200)
        desc_ids = [item["item_id"] for item in desc.json()["items"]]
        self.assertEqual(
            desc_ids,
            [self.trade_item_id, high_id, low_id, override_id],
        )

    def test_public_trade_resolves_full_rarity_name_from_code_not_printing_label(self):
        session = self.Session()
        card = Card(id=83994646, name="4-Starred Ladybug of Doom")
        session.add(card)
        printing = Printing(
            card_id=card.id,
            set_code="DB1-EN198",
            set_rarity_code="(C)",
            set_rarity="C",
        )
        session.add(printing)
        session.flush()
        trade_item = CollectionItem(
            user_id=self.owner.id,
            set_code="DB1-EN198",
            rarity_code="(C)",
            card_name=card.name,
            quantity=2,
            trade_quantity=2,
            condition="NearMint",
            printing_id=printing.id,
        )
        session.add(trade_item)
        session.commit()
        session.close()

        response = self.client.get("/api/public/trade/owner-trade-list")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 2)
        common_item = next(
            item for item in payload["items"] if item["set_code"] == "DB1-EN198"
        )
        self.assertEqual(common_item["rarity_code"], "(C)")
        self.assertEqual(common_item["rarity_display"], "C")
        self.assertEqual(common_item["rarity_name"], "Common")

    def test_invalid_slug_returns_404(self):
        response = self.client.get("/api/public/trade/does-not-exist")
        self.assertEqual(response.status_code, 404)

    def test_public_trade_filters(self):
        response = self.client.get("/api/public/trade/owner-trade-list/filters")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["sets"],
            [{"expansion_code": "LOB", "set_name": None}],
        )
        self.assertEqual(payload["conditions"], ["NearMint"])
        self.assertEqual(
            payload["rarities"],
            [{"rarity_code": "(UR)", "rarity_name": "Ultra Rare"}],
        )

    def test_public_trade_filters_by_expansion_code(self):
        session = self.Session()
        card = Card(id=83994646, name="4-Starred Ladybug of Doom")
        session.add(card)
        session.add(
            Printing(
                card_id=card.id,
                set_code="DB1-EN198",
                set_rarity_code="(C)",
                set_rarity="C",
            )
        )
        session.flush()
        session.add(
            CollectionItem(
                user_id=self.owner.id,
                set_code="DB1-EN198",
                expansion_code="DB1",
                rarity_code="(C)",
                card_name=card.name,
                quantity=2,
                trade_quantity=2,
                condition="NearMint",
            )
        )
        session.commit()
        session.close()

        filters = self.client.get("/api/public/trade/owner-trade-list/filters")
        self.assertEqual(filters.status_code, 200)
        self.assertEqual(
            sorted(row["expansion_code"] for row in filters.json()["sets"]),
            ["DB1", "LOB"],
        )

        response = self.client.get("/api/public/trade/owner-trade-list?set_code=DB1")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["set_code"], "DB1-EN198")

        other = self.client.get("/api/public/trade/owner-trade-list?set_code=LOB")
        self.assertEqual(other.status_code, 200)
        self.assertEqual(other.json()["total"], 1)
        self.assertEqual(other.json()["items"][0]["set_code"], "LOB-001")

    def test_public_trade_filters_by_rarity(self):
        session = self.Session()
        card = Card(id=83994646, name="4-Starred Ladybug of Doom")
        session.add(card)
        session.add(
            Printing(
                card_id=card.id,
                set_code="DB1-EN198",
                set_rarity_code="(C)",
                set_rarity="C",
            )
        )
        session.flush()
        session.add(
            CollectionItem(
                user_id=self.owner.id,
                set_code="DB1-EN198",
                expansion_code="DB1",
                rarity_code="(C)",
                card_name=card.name,
                quantity=2,
                trade_quantity=2,
                condition="NearMint",
            )
        )
        session.commit()
        session.close()

        filters = self.client.get("/api/public/trade/owner-trade-list/filters")
        self.assertEqual(filters.status_code, 200)
        self.assertEqual(
            sorted(filters.json()["rarities"], key=lambda row: row["rarity_name"]),
            [
                {"rarity_code": "(C)", "rarity_name": "Common"},
                {"rarity_code": "(UR)", "rarity_name": "Ultra Rare"},
            ],
        )

        ultra = self.client.get("/api/public/trade/owner-trade-list?rarity=(UR)")
        self.assertEqual(ultra.status_code, 200)
        self.assertEqual(ultra.json()["total"], 1)
        self.assertEqual(ultra.json()["items"][0]["set_code"], "LOB-001")

        common = self.client.get("/api/public/trade/owner-trade-list?rarity=(C)")
        self.assertEqual(common.status_code, 200)
        self.assertEqual(common.json()["total"], 1)
        self.assertEqual(common.json()["items"][0]["set_code"], "DB1-EN198")

        combined = self.client.get(
            "/api/public/trade/owner-trade-list?set_code=DB1&rarity=(C)"
        )
        self.assertEqual(combined.status_code, 200)
        self.assertEqual(combined.json()["total"], 1)
        self.assertEqual(combined.json()["items"][0]["set_code"], "DB1-EN198")

        no_match = self.client.get(
            "/api/public/trade/owner-trade-list?set_code=LOB&rarity=(C)"
        )
        self.assertEqual(no_match.status_code, 200)
        self.assertEqual(no_match.json()["total"], 0)

    def test_public_trade_filters_normalize_bad_expansion_code(self):
        session = self.Session()
        card = Card(id=34536976, name="A.I. Challenge You")
        session.add(card)
        session.add(
            Printing(
                card_id=card.id,
                set_code="LIOV-EN076",
                set_rarity_code="(C)",
                set_rarity="C",
            )
        )
        session.flush()
        session.add(
            CollectionItem(
                user_id=self.owner.id,
                set_code="LIOV-EN076",
                expansion_code="LIOV-EN076",
                rarity_code="(C)",
                card_name=card.name,
                quantity=4,
                trade_quantity=4,
                condition="NearMint",
            )
        )
        session.commit()
        session.close()

        response = self.client.get("/api/public/trade/owner-trade-list/filters")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted(row["expansion_code"] for row in response.json()["sets"]),
            ["LIOV", "LOB"],
        )

        filtered = self.client.get("/api/public/trade/owner-trade-list?set_code=LIOV")
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["total"], 1)
        self.assertEqual(filtered.json()["items"][0]["set_code"], "LIOV-EN076")

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
        self.assertIn("/legal/terms", trade.text)

        privacy = self.client.get("/legal/privacy")
        self.assertEqual(privacy.status_code, 200)
        self.assertIn("Brevo", privacy.text)
        self.assertIn("/legal/terms", privacy.text)

        imprint = self.client.get("/legal/imprint")
        self.assertEqual(imprint.status_code, 200)

        terms = self.client.get("/legal/terms")
        self.assertEqual(terms.status_code, 200)
        self.assertIn("request relay", terms.text.lower())

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
