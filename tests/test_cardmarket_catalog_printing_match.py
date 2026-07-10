"""Printing match helpers for Cardmarket catalog."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.cardmarket.catalog.expansion_map import ExpansionMapping
from ygo_app.cardmarket.catalog.printing_match import (
    _dedupe_cm_matches_by_expansion_preference,
    match_printings_to_catalog,
)
from ygo_app.models import Base, Card, Printing, RarityPriceRank


def _sqlite_engine(path: str):
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return eng


class TestCardmarketCatalogPrintingMatch(unittest.TestCase):
    def test_dedupes_duplicate_card_across_expansions_to_dominant(self):
        cm_matches = [
            {"idProduct": 1, "name": "Bujintei Susanowo", "idExpansion": 1497},
            {"idProduct": 2, "name": "Bujintei Susanowo", "idExpansion": 1498},
        ]
        deduped = _dedupe_cm_matches_by_expansion_preference(
            cm_matches,
            expansion_match_counts={1497: 1, 1498: 5},
        )
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["idExpansion"], 1498)

    def test_keeps_all_when_no_match_counts(self):
        cm_matches = [
            {"idProduct": 1, "name": "Card", "idExpansion": 1497},
            {"idProduct": 2, "name": "Card", "idExpansion": 1498},
        ]
        deduped = _dedupe_cm_matches_by_expansion_preference(
            cm_matches,
            expansion_match_counts=None,
        )
        self.assertEqual(deduped, cm_matches)

    def test_keeps_all_when_dominant_expansion_ties(self):
        cm_matches = [
            {"idProduct": 1, "name": "Card", "idExpansion": 1497},
            {"idProduct": 2, "name": "Card", "idExpansion": 1498},
        ]
        deduped = _dedupe_cm_matches_by_expansion_preference(
            cm_matches,
            expansion_match_counts={1497: 3, 1498: 3},
        )
        self.assertEqual(deduped, cm_matches)

    def test_rejects_bad_card_and_exports_sibling(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        engine = _sqlite_engine(tmp.name)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        session.add(RarityPriceRank(sort_order=1, name="Common", rarity_code="C"))
        session.add(RarityPriceRank(sort_order=18, name="Ultra Rare", rarity_code="UR"))
        session.add(Card(id=1, name="Good Card"))
        session.add(Card(id=2, name="Bad Card"))
        session.add(
            Printing(
                card_id=1,
                set_code="TST-EN001",
                set_rarity="Common",
                set_rarity_code="C",
            )
        )
        session.add(
            Printing(
                card_id=2,
                set_code="TST-EN002",
                set_rarity="Common",
                set_rarity_code="C",
            )
        )
        session.add(
            Printing(
                card_id=2,
                set_code="TST-EN002",
                set_rarity="Ultra Rare",
                set_rarity_code="UR",
            )
        )
        session.commit()

        singles = [
            {
                "idProduct": 101,
                "name": "Good Card",
                "idCategory": 5,
                "idExpansion": 9001,
            },
            {
                "idProduct": 201,
                "name": "Bad Card",
                "idCategory": 5,
                "idExpansion": 9001,
            },
        ]
        prices = [
            {"idProduct": 101, "trend": 1.0, "avg": 1.0, "low": 0.5},
            {"idProduct": 201, "trend": 2.0, "avg": 2.0, "low": 1.0},
        ]
        mappings = {
            "TST": ExpansionMapping(
                abbr="TST",
                set_name="Test Set",
                expansion_ids=(9001,),
                matched_product_names=["Test Set Booster"],
            )
        }

        export_rows, stats, rejections = match_printings_to_catalog(
            session,
            singles=singles,
            price_rows=prices,
            expansion_mappings=mappings,
        )
        session.close()
        engine.dispose()

        self.assertEqual(len(export_rows), 1)
        self.assertEqual(export_rows[0]["set_code"], "TST-EN001")
        self.assertEqual(stats["matched"], 1)
        self.assertEqual(stats["rejected_cards"], 1)
        self.assertEqual(len(rejections), 1)
        self.assertEqual(rejections[0]["reason"], "count_mismatch")
        self.assertEqual(rejections[0]["card_name"], "Bad Card")


if __name__ == "__main__":
    unittest.main()
