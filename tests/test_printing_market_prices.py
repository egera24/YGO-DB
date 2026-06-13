"""Printing market prices DB join and catalog import survival."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from ygo_app.cardmarket.constants import DISCOVERY_MATCHED
from ygo_app.cardmarket.market_prices import attach_market_prices_to_printings, load_market_prices, upsert_market_price
from ygo_app.import_data import import_cards_entries
from ygo_app.models import Base, Card, Printing, PrintingMarketPrice
from ygo_app.services import get_card_detail


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


class TestPrintingMarketPrices(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.engine = _sqlite_engine(self.tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

        card = Card(id=85087012, name="Card Trooper")
        self.session.add(card)
        self.session.add(
            Printing(
                card_id=card.id,
                set_code="ANPR-ENSE1",
                set_rarity="Super Rare",
                set_rarity_code="SR",
                set_name="Ancient Prophecy",
            )
        )
        self.session.add(
            PrintingMarketPrice(
                set_code="ANPR-ENSE1",
                rarity_code="SR",
                cardmarket_product_id=999,
                cardmarket_url="https://example.com/solar",
                low_price=0.5,
                avg_price=0.75,
                trend_price=1.2,
                currency="EUR",
                discovery_status=DISCOVERY_MATCHED,
                updated_at=datetime.utcnow(),
            )
        )
        self.session.commit()

        self.session_factory_patcher = patch(
            "ygo_app.import_data.SessionLocal", self.Session
        )
        self.init_db_patcher = patch("ygo_app.import_data.init_db", lambda: None)
        self.session_factory_patcher.start()
        self.init_db_patcher.start()

    def tearDown(self):
        self.init_db_patcher.stop()
        self.session_factory_patcher.stop()
        self.session.close()
        self.engine.dispose()

    def test_attach_market_prices_to_printings(self):
        card = self.session.get(Card, 85087012)
        printings = list(self.session.scalars(select(Printing)))
        attach_market_prices_to_printings(self.session, printings)
        p = printings[0]
        self.assertAlmostEqual(p.low_price, 0.5)
        self.assertAlmostEqual(p.avg_price, 0.75)
        self.assertAlmostEqual(p.trend_price, 1.2)
        self.assertEqual(p.price_currency, "EUR")

    def test_get_card_detail_includes_market_prices(self):
        detail = get_card_detail(self.session, 85087012, None)
        self.assertIsNotNone(detail)
        p = detail.printings[0]
        self.assertAlmostEqual(p.low_price, 0.5)
        self.assertAlmostEqual(p.trend_price, 1.2)

    def test_prices_survive_catalog_reimport(self):
        entries = [
            {
                "id": 85087012,
                "name": "Card Trooper",
                "card_sets": [
                    {
                        "set_code": "ANPR-ENSE1",
                        "set_name": "Ancient Prophecy",
                        "set_rarity": "Super Rare",
                        "set_rarity_code": "SR",
                    }
                ],
            }
        ]
        import_cards_entries(entries)
        prices = load_market_prices(self.session, [("ANPR-ENSE1", "SR")])
        self.assertIn(("ANPR-ENSE1", "SR"), prices)
        self.assertAlmostEqual(prices[("ANPR-ENSE1", "SR")].avg_price, 0.75)

    def test_upsert_updates_prices(self):
        upsert_market_price(
            self.session,
            set_code="ANPR-ENSE1",
            rarity_code="SR",
            low_price=0.6,
            avg_price=0.8,
            trend_price=1.3,
            update_prices=True,
        )
        self.session.commit()
        row = self.session.get(PrintingMarketPrice, {"set_code": "ANPR-ENSE1", "rarity_code": "SR"})
        self.assertAlmostEqual(row.low_price, 0.6)


if __name__ == "__main__":
    unittest.main()
