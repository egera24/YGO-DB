"""Print-variant collapse for Cardmarket catalog matching."""

from __future__ import annotations

import tempfile
import unittest

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.cardmarket.catalog.expansion_map import ExpansionMapping
from ygo_app.cardmarket.catalog.print_variants import (
    collapse_cm_print_variants,
    split_consecutive_id_runs,
)
from ygo_app.cardmarket.catalog.printing_match import match_printings_to_catalog
from ygo_app.models import Base, Card, Printing, RarityPriceRank


def _sqlite_engine(path: str):
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return eng


def _single_row(
    *,
    id_product: int,
    name: str,
    id_expansion: int,
    id_metacard: int = 0,
) -> dict:
    return {
        "idProduct": id_product,
        "name": name,
        "idCategory": 5,
        "idExpansion": id_expansion,
        "idMetacard": id_metacard,
    }


def _price_index(*rows: tuple[int, float]) -> dict[int, dict]:
    return {id_product: {"avg": avg} for id_product, avg in rows}


class TestSplitConsecutiveIdRuns(unittest.TestCase):
    def test_splits_25lp_diabellstar_batches(self):
        rows = [
            _single_row(id_product=845460, name="Card", id_expansion=6212),
            _single_row(id_product=845461, name="Card", id_expansion=6212),
            _single_row(id_product=845520, name="Card", id_expansion=6212),
            _single_row(id_product=845521, name="Card", id_expansion=6212),
        ]
        runs = split_consecutive_id_runs(rows)
        self.assertEqual(len(runs), 2)
        self.assertEqual([row["idProduct"] for row in runs[0]], [845460, 845461])
        self.assertEqual([row["idProduct"] for row in runs[1]], [845520, 845521])

    def test_splits_ra05_raigeki_prefix_and_block(self):
        rows = [
            _single_row(id_product=881339, name="Raigeki", id_expansion=6424),
            _single_row(id_product=881340, name="Raigeki", id_expansion=6424),
            _single_row(id_product=882204, name="Raigeki", id_expansion=6424),
            _single_row(id_product=882206, name="Raigeki", id_expansion=6424),
            _single_row(id_product=882208, name="Raigeki", id_expansion=6424),
            _single_row(id_product=882209, name="Raigeki", id_expansion=6424),
            _single_row(id_product=882211, name="Raigeki", id_expansion=6424),
            _single_row(id_product=882212, name="Raigeki", id_expansion=6424),
            _single_row(id_product=882213, name="Raigeki", id_expansion=6424),
        ]
        runs = split_consecutive_id_runs(rows)
        self.assertEqual(len(runs), 2)
        self.assertEqual([row["idProduct"] for row in runs[0]], [881339, 881340])
        self.assertEqual(
            [row["idProduct"] for row in runs[1]],
            [882204, 882206, 882208, 882209, 882211, 882212, 882213],
        )


class TestCollapseCmPrintVariants(unittest.TestCase):
    def test_25lp_diabellstar_keeps_cheaper_normal_pair(self):
        rows = [
            _single_row(
                id_product=845460,
                name="Diabellstar the Black Witch",
                id_expansion=6212,
                id_metacard=422344,
            ),
            _single_row(
                id_product=845461,
                name="Diabellstar the Black Witch",
                id_expansion=6212,
                id_metacard=422344,
            ),
            _single_row(
                id_product=845520,
                name="Diabellstar the Black Witch",
                id_expansion=6212,
                id_metacard=422344,
            ),
            _single_row(
                id_product=845521,
                name="Diabellstar the Black Witch",
                id_expansion=6212,
                id_metacard=422344,
            ),
        ]
        prices = _price_index(
            (845460, 0.66),
            (845461, 1.42),
            (845520, 1.08),
            (845521, 3.41),
        )
        collapsed = collapse_cm_print_variants(rows, target_count=2, price_index=prices)
        self.assertEqual([row["idProduct"] for row in collapsed], [845460, 845461])

    def test_25lp_exodia_noop_when_already_two(self):
        rows = [
            _single_row(
                id_product=845458,
                name="Exodia the Forbidden One",
                id_expansion=6212,
                id_metacard=102696,
            ),
            _single_row(
                id_product=845459,
                name="Exodia the Forbidden One",
                id_expansion=6212,
                id_metacard=102696,
            ),
        ]
        prices = _price_index((845458, 70.0), (845459, 500.0))
        collapsed = collapse_cm_print_variants(rows, target_count=2, price_index=prices)
        self.assertEqual([row["idProduct"] for row in collapsed], [845458, 845459])

    def test_ra05_raigeki_drops_prefix_pair(self):
        rows = [
            _single_row(id_product=881339, name="Raigeki", id_expansion=6424, id_metacard=103757),
            _single_row(id_product=881340, name="Raigeki", id_expansion=6424, id_metacard=103757),
            _single_row(id_product=882204, name="Raigeki", id_expansion=6424, id_metacard=103757),
            _single_row(id_product=882206, name="Raigeki", id_expansion=6424, id_metacard=103757),
            _single_row(id_product=882208, name="Raigeki", id_expansion=6424, id_metacard=103757),
            _single_row(id_product=882209, name="Raigeki", id_expansion=6424, id_metacard=103757),
            _single_row(id_product=882211, name="Raigeki", id_expansion=6424, id_metacard=103757),
            _single_row(id_product=882212, name="Raigeki", id_expansion=6424, id_metacard=103757),
            _single_row(id_product=882213, name="Raigeki", id_expansion=6424, id_metacard=103757),
        ]
        prices = _price_index(
            (881339, 0.58),
            (881340, 3.9),
            (882204, 0.3),
            (882206, 0.28),
            (882208, 0.42),
            (882209, 1.0),
            (882211, 4.22),
            (882212, 1.79),
            (882213, 1.19),
        )
        collapsed = collapse_cm_print_variants(rows, target_count=7, price_index=prices)
        self.assertEqual(
            [row["idProduct"] for row in collapsed],
            [882204, 882206, 882208, 882209, 882211, 882212, 882213],
        )

    def test_ambiguous_structure_leaves_rows_unchanged(self):
        rows = [
            _single_row(id_product=100, name="Card", id_expansion=1),
            _single_row(id_product=101, name="Card", id_expansion=1),
            _single_row(id_product=200, name="Card", id_expansion=1),
            _single_row(id_product=300, name="Card", id_expansion=1),
            _single_row(id_product=301, name="Card", id_expansion=1),
        ]
        prices = _price_index(
            (100, 1.0),
            (101, 2.0),
            (200, 3.0),
            (300, 4.0),
            (301, 5.0),
        )
        collapsed = collapse_cm_print_variants(rows, target_count=2, price_index=prices)
        self.assertEqual([row["idProduct"] for row in collapsed], [100, 101, 200, 300, 301])


class TestPrintVariantPrintingMatchIntegration(unittest.TestCase):
    def test_25lp_style_card_matches_after_variant_collapse(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        engine = _sqlite_engine(tmp.name)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        session.add(RarityPriceRank(sort_order=18, name="Ultra Rare", rarity_code="UR"))
        session.add(RarityPriceRank(sort_order=20, name="Secret Rare", rarity_code="ScR"))
        session.add(Card(id=1, name="Diabellstar the Black Witch"))
        session.add(
            Printing(
                card_id=1,
                set_code="25LP-EN001",
                set_rarity="Ultra Rare",
                set_rarity_code="UR",
            )
        )
        session.add(
            Printing(
                card_id=1,
                set_code="25LP-EN001",
                set_rarity="Secret Rare",
                set_rarity_code="ScR",
            )
        )
        session.commit()

        singles = [
            _single_row(
                id_product=845460,
                name="Diabellstar the Black Witch",
                id_expansion=6212,
                id_metacard=422344,
            ),
            _single_row(
                id_product=845461,
                name="Diabellstar the Black Witch",
                id_expansion=6212,
                id_metacard=422344,
            ),
            _single_row(
                id_product=845520,
                name="Diabellstar the Black Witch",
                id_expansion=6212,
                id_metacard=422344,
            ),
            _single_row(
                id_product=845521,
                name="Diabellstar the Black Witch",
                id_expansion=6212,
                id_metacard=422344,
            ),
        ]
        prices = [
            {"idProduct": 845460, "trend": 0.58, "avg": 0.66, "low": 0.02},
            {"idProduct": 845461, "trend": 1.35, "avg": 1.42, "low": 0.49},
            {"idProduct": 845520, "trend": 0.89, "avg": 1.08, "low": 0.2},
            {"idProduct": 845521, "trend": 3.41, "avg": 3.41, "low": 2.9},
        ]
        mappings = {
            "25LP": ExpansionMapping(
                abbr="25LP",
                set_name="Limited Pack World Championship 2025",
                expansion_ids=(6212,),
                matched_product_names=["Limited Pack World Championship 2025 Booster"],
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
        self.assertEqual(stats["matched"], 2)
        by_code = {(row["set_code"], row["rarity_code"]): row for row in export_rows}
        self.assertEqual(by_code[("25LP-EN001", "UR")]["cardmarket_product_id"], 845460)
        self.assertEqual(by_code[("25LP-EN001", "ScR")]["cardmarket_product_id"], 845461)


if __name__ == "__main__":
    unittest.main()
