"""Printing match helpers for Cardmarket catalog."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.cardmarket.catalog.expansion_map import ExpansionMapping
from ygo_app.cardmarket.catalog.printing_match import (
    _dedupe_cm_matches_by_expansion_preference,
    _fallback_parenthetical_suffix_keys,
    _parenthetical_suffix_key_matches,
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
    def test_parenthetical_suffix_key_matches_skill_suffix(self):
        self.assertTrue(
            _parenthetical_suffix_key_matches("catch of the day (skill)", "catch of the day")
        )

    def test_parenthetical_suffix_key_rejects_prefix_mismatch(self):
        self.assertFalse(
            _parenthetical_suffix_key_matches(
                "super catch of the day (skill)",
                "catch of the day",
            )
        )

    def test_parenthetical_suffix_key_rejects_unparenthesized_word(self):
        self.assertFalse(
            _parenthetical_suffix_key_matches("catch of the day skill", "catch of the day")
        )

    def test_fallback_parenthetical_suffix_keys_matches_raw_skill_name(self):
        cm_rows = [
            {
                "idProduct": 732282,
                "name": "Catch of the Day (Skill)",
                "idCategory": 5,
                "idExpansion": 5397,
            }
        ]
        cm_by_card_name = {"catch of the day skill": cm_rows}
        matches = _fallback_parenthetical_suffix_keys(
            cm_by_card_name,
            "catch of the day",
            cm_rows=cm_rows,
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["idProduct"], 732282)

    def test_matches_skill_card_with_parenthetical_cardmarket_name(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        engine = _sqlite_engine(tmp.name)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        session.add(RarityPriceRank(sort_order=1, name="Common", rarity_code="C"))
        session.add(Card(id=1, name="Catch of the Day"))
        session.add(
            Printing(
                card_id=1,
                set_code="SBAD-EN001",
                set_rarity="Common",
                set_rarity_code="C",
            )
        )
        session.commit()

        singles = [
            {
                "idProduct": 732282,
                "name": "Catch of the Day (Skill)",
                "idCategory": 5,
                "idExpansion": 5397,
                "idMetacard": 271230,
            }
        ]
        prices = [
            {"idProduct": 732282, "trend": 0.22, "avg": 0.33, "low": 0.2},
        ]
        mappings = {
            "SBAD": ExpansionMapping(
                abbr="SBAD",
                set_name="Speed Duel: Attack from the Deep",
                expansion_ids=(5397,),
                matched_product_names=["Speed Duel: Attack from the Deep Booster Box"],
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

        self.assertEqual(rejections, [])
        self.assertEqual(len(export_rows), 1)
        self.assertEqual(export_rows[0]["set_code"], "SBAD-EN001")
        self.assertEqual(export_rows[0]["cardmarket_product_id"], 732282)
        self.assertEqual(stats["matched"], 1)

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

    def test_ys11_grenosaurus_prunes_incomplete_duplicate_listing(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        engine = _sqlite_engine(tmp.name)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        session.add(RarityPriceRank(sort_order=1, name="Common", rarity_code="C"))
        session.add(Card(id=1, name="Grenosaurus"))
        session.add(
            Printing(
                card_id=1,
                set_code="YS11-EN038",
                set_rarity="Common",
                set_rarity_code="C",
            )
        )
        session.commit()

        singles = [
            {
                "idProduct": 248156,
                "name": "Grenosaurus",
                "idCategory": 5,
                "idExpansion": 1282,
                "idMetacard": 203573,
            },
            {
                "idProduct": 327224,
                "name": "Grenosaurus",
                "idCategory": 5,
                "idExpansion": 1282,
                "idMetacard": 203573,
            },
        ]
        prices = [
            {"idProduct": 248156, "trend": 0.12, "avg": 0.21, "low": 0.02},
            {"idProduct": 327224, "trend": 5.0, "avg": 5.0, "low": None},
        ]
        mappings = {
            "YS11": ExpansionMapping(
                abbr="YS11",
                set_name="Starter Deck: Dawn of the Xyz",
                expansion_ids=(1282,),
                matched_product_names=["Starter Deck: Dawn of the Xyz"],
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

        self.assertEqual(rejections, [])
        self.assertEqual(len(export_rows), 1)
        self.assertEqual(export_rows[0]["set_code"], "YS11-EN038")
        self.assertEqual(export_rows[0]["cardmarket_product_id"], 248156)
        self.assertEqual(export_rows[0]["low_price"], 0.02)
        self.assertEqual(stats["matched"], 1)

    def test_rejects_overcount_when_all_cm_prices_complete(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        engine = _sqlite_engine(tmp.name)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        session.add(RarityPriceRank(sort_order=1, name="Common", rarity_code="C"))
        session.add(Card(id=1, name="Overcount Card"))
        session.add(
            Printing(
                card_id=1,
                set_code="TST-EN001",
                set_rarity="Common",
                set_rarity_code="C",
            )
        )
        session.commit()

        singles = [
            {
                "idProduct": 101,
                "name": "Overcount Card",
                "idCategory": 5,
                "idExpansion": 9001,
                "idMetacard": 5001,
            },
            {
                "idProduct": 102,
                "name": "Overcount Card",
                "idCategory": 5,
                "idExpansion": 9001,
                "idMetacard": 5001,
            },
        ]
        prices = [
            {"idProduct": 101, "trend": 1.0, "avg": 1.0, "low": 0.5},
            {"idProduct": 102, "trend": 2.0, "avg": 2.0, "low": 1.0},
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

        self.assertEqual(export_rows, [])
        self.assertEqual(stats["rejected_cards"], 1)
        self.assertEqual(len(rejections), 1)
        self.assertEqual(rejections[0]["reason"], "count_mismatch")
        self.assertEqual(rejections[0]["card_name"], "Overcount Card")


if __name__ == "__main__":
    unittest.main()
