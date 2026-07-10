"""Regional variant grouping and catalog price broadcast."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.cardmarket.catalog.expansion_map import ExpansionMapping
from ygo_app.cardmarket.catalog.printing_match import match_printings_to_catalog
from ygo_app.cardmarket.catalog.rarity_guess import YugipediaPrintingRef
from ygo_app.cardmarket.catalog.regional_variants import (
    collector_slot_key,
    group_regional_variant_refs,
    parse_yugipedia_set_code,
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


def _seed_session(session) -> None:
    session.add(RarityPriceRank(sort_order=1, name="Common", rarity_code="C"))
    session.add(RarityPriceRank(sort_order=18, name="Ultra Rare", rarity_code="UR"))


class TestRegionalVariantParsing(unittest.TestCase):
    def test_parse_lod_regional_codes(self):
        self.assertEqual(parse_yugipedia_set_code("LOD-078"), ("LOD", "078"))
        self.assertEqual(parse_yugipedia_set_code("LOD-EN078"), ("LOD", "078"))

    def test_collector_slot_key_groups_regional_duplicates(self):
        self.assertEqual(collector_slot_key("LOD-078", "C"), ("C", "78"))
        self.assertEqual(collector_slot_key("LOD-EN078", "C"), ("C", "78"))

    def test_different_collector_numbers_stay_separate(self):
        self.assertNotEqual(
            collector_slot_key("LOD-078", "C"),
            collector_slot_key("LOD-079", "C"),
        )


class TestGroupRegionalVariantRefs(unittest.TestCase):
    def test_groups_lod_regional_commons(self):
        refs = [
            YugipediaPrintingRef("LOD-078", "C", "Common", "A Legendary Ocean", 1, 1),
            YugipediaPrintingRef("LOD-EN078", "C", "Common", "A Legendary Ocean", 1, 1),
        ]
        groups = group_regional_variant_refs(refs)
        self.assertEqual(len(groups), 1)
        rep, variants = groups[0]
        self.assertEqual(rep.set_code, "LOD-EN078")
        self.assertEqual({v.set_code for v in variants}, {"LOD-078", "LOD-EN078"})

    def test_multi_rarity_regional_groups(self):
        refs = [
            YugipediaPrintingRef("LOD-078", "C", "Common", "Card", 1, 1),
            YugipediaPrintingRef("LOD-EN078", "C", "Common", "Card", 1, 1),
            YugipediaPrintingRef("LOD-079", "UR", "Ultra Rare", "Card", 1, 18),
            YugipediaPrintingRef("LOD-EN079", "UR", "Ultra Rare", "Card", 1, 18),
        ]
        groups = group_regional_variant_refs(refs)
        self.assertEqual(len(groups), 2)
        reps = {rep.set_code for rep, _ in groups}
        self.assertEqual(reps, {"LOD-EN078", "LOD-EN079"})


class TestRegionalCatalogMatch(unittest.TestCase):
    def _run_match(self, printings: list[Printing], singles: list[dict], prices: list[dict]):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        engine = _sqlite_engine(tmp.name)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        _seed_session(session)
        for printing in printings:
            session.add(printing)
        session.commit()

        mappings = {
            "LOD": ExpansionMapping(
                abbr="LOD",
                set_name="Legacy of Darkness",
                expansion_ids=(1026,),
                matched_product_names=["Legacy of Darkness Booster"],
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
        return export_rows, stats, rejections

    def test_lod_regional_broadcast_single_cm_product(self):
        card = Card(id=1, name="A Legendary Ocean")
        printings = [
            Printing(
                card=card,
                card_id=1,
                set_code="LOD-078",
                set_rarity="Common",
                set_rarity_code="C",
            ),
            Printing(
                card=card,
                card_id=1,
                set_code="LOD-EN078",
                set_rarity="Common",
                set_rarity_code="C",
            ),
        ]
        singles = [
            {
                "idProduct": 101814,
                "name": "A Legendary Ocean",
                "idCategory": 5,
                "idExpansion": 1026,
            }
        ]
        prices = [
            {"idProduct": 101814, "trend": 0.41, "avg": 0.19, "low": 0.02},
        ]

        export_rows, stats, rejections = self._run_match(printings, singles, prices)

        self.assertEqual(rejections, [])
        self.assertEqual(stats["matched"], 2)
        self.assertEqual(len(export_rows), 2)
        by_code = {row["set_code"]: row for row in export_rows}
        self.assertIn("LOD-078", by_code)
        self.assertIn("LOD-EN078", by_code)
        for code in ("LOD-078", "LOD-EN078"):
            row = by_code[code]
            self.assertEqual(row["cardmarket_product_id"], 101814)
            self.assertEqual(row["low_price"], 0.02)
            self.assertEqual(row["avg_price"], 0.19)
            self.assertEqual(row["trend_price"], 0.41)

    def test_lod_regional_broadcast_drops_sparse_duplicate_cm_listing(self):
        card = Card(id=1, name="A Legendary Ocean")
        printings = [
            Printing(
                card=card,
                card_id=1,
                set_code="LOD-078",
                set_rarity="Common",
                set_rarity_code="C",
            ),
            Printing(
                card=card,
                card_id=1,
                set_code="LOD-EN078",
                set_rarity="Common",
                set_rarity_code="C",
            ),
        ]
        singles = [
            {
                "idProduct": 101814,
                "name": "A Legendary Ocean",
                "idCategory": 5,
                "idExpansion": 1026,
                "idMetacard": 101793,
            },
            {
                "idProduct": 581273,
                "name": "A Legendary Ocean",
                "idCategory": 5,
                "idExpansion": 1026,
                "idMetacard": 101793,
            },
        ]
        prices = [
            {"idProduct": 101814, "trend": 0.38, "avg": 0.19, "low": 0.02},
            {"idProduct": 581273, "trend": 0.04, "avg": None, "low": 0.02},
        ]

        export_rows, stats, rejections = self._run_match(printings, singles, prices)

        self.assertEqual(rejections, [])
        self.assertEqual(stats["matched"], 2)
        by_code = {row["set_code"]: row for row in export_rows}
        self.assertEqual(by_code["LOD-078"]["cardmarket_product_id"], 101814)
        self.assertEqual(by_code["LOD-EN078"]["avg_price"], 0.19)
        self.assertEqual(by_code["LOD-EN078"]["trend_price"], 0.38)

    def test_multi_rarity_regional_broadcast(self):
        card = Card(id=1, name="Dual Rarity Card")
        printings = [
            Printing(card=card, card_id=1, set_code="LOD-078", set_rarity="Common", set_rarity_code="C"),
            Printing(
                card=card, card_id=1, set_code="LOD-EN078", set_rarity="Common", set_rarity_code="C"
            ),
            Printing(
                card=card, card_id=1, set_code="LOD-079", set_rarity="Ultra Rare", set_rarity_code="UR"
            ),
            Printing(
                card=card,
                card_id=1,
                set_code="LOD-EN079",
                set_rarity="Ultra Rare",
                set_rarity_code="UR",
            ),
        ]
        singles = [
            {
                "idProduct": 501,
                "name": "Dual Rarity Card",
                "idCategory": 5,
                "idExpansion": 1026,
            },
            {
                "idProduct": 502,
                "name": "Dual Rarity Card",
                "idCategory": 5,
                "idExpansion": 1026,
            },
        ]
        prices = [
            {"idProduct": 501, "trend": 0.10, "avg": 0.08, "low": 0.02},
            {"idProduct": 502, "trend": 2.00, "avg": 1.50, "low": 0.50},
        ]

        export_rows, stats, rejections = self._run_match(printings, singles, prices)

        self.assertEqual(rejections, [])
        self.assertEqual(stats["matched"], 4)
        by_code = {row["set_code"]: row for row in export_rows}
        self.assertEqual(by_code["LOD-078"]["trend_price"], 0.10)
        self.assertEqual(by_code["LOD-EN078"]["trend_price"], 0.10)
        self.assertEqual(by_code["LOD-079"]["trend_price"], 2.00)
        self.assertEqual(by_code["LOD-EN079"]["trend_price"], 2.00)
        self.assertEqual(by_code["LOD-078"]["cardmarket_product_id"], 501)
        self.assertEqual(by_code["LOD-EN079"]["cardmarket_product_id"], 502)

    def test_different_collector_numbers_not_collapsed(self):
        card = Card(id=1, name="Two Slots Card")
        printings = [
            Printing(card=card, card_id=1, set_code="LOD-078", set_rarity="Common", set_rarity_code="C"),
            Printing(card=card, card_id=1, set_code="LOD-079", set_rarity="Common", set_rarity_code="C"),
        ]
        singles = [
            {
                "idProduct": 601,
                "name": "Two Slots Card",
                "idCategory": 5,
                "idExpansion": 1026,
            }
        ]
        prices = [{"idProduct": 601, "trend": 1.0, "avg": 1.0, "low": 0.5}]

        export_rows, stats, rejections = self._run_match(printings, singles, prices)

        self.assertEqual(export_rows, [])
        self.assertEqual(stats["rejected_cards"], 1)
        self.assertEqual(rejections[0]["reason"], "count_mismatch")

    def test_true_multi_rarity_mismatch_still_rejects(self):
        card = Card(id=1, name="Bad Card")
        printings = [
            Printing(card=card, card_id=1, set_code="TST-EN002", set_rarity="Common", set_rarity_code="C"),
            Printing(
                card=card, card_id=1, set_code="TST-EN002", set_rarity="Ultra Rare", set_rarity_code="UR"
            ),
        ]
        singles = [
            {"idProduct": 201, "name": "Bad Card", "idCategory": 5, "idExpansion": 9001},
        ]
        prices = [{"idProduct": 201, "trend": 2.0, "avg": 2.0, "low": 1.0}]

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        engine = _sqlite_engine(tmp.name)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        _seed_session(session)
        for printing in printings:
            session.add(printing)
        session.commit()

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
        self.assertEqual(rejections[0]["reason"], "count_mismatch")
        self.assertEqual(rejections[0]["card_name"], "Bad Card")


if __name__ == "__main__":
    unittest.main()
