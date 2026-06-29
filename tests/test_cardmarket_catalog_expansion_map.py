"""Expansion mapping from Cardmarket nonsingles catalog."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ygo_app.cardmarket.catalog.expansion_map import map_expansions_from_nonsingles
from ygo_app.cardmarket.catalog.expansion_aliases import nonsingle_matches_alias
from ygo_app.cardmarket.catalog.normalize import (
    dark_revelation_cardmarket_name,
    legendary_duelists_subtitle_name,
    starter_deck_cardmarket_name,
    structure_deck_cardmarket_name,
)
from ygo_app.models import Base, Card, Printing, TcgSet


def _sqlite_engine(path: str):
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return eng


class TestCardmarketCatalogExpansionMap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.engine = _sqlite_engine(self.tmp.name)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()

        fixture = Path(__file__).resolve().parent / "fixtures" / "cardmarket" / "nonsingles_snippet.json"
        self.nonsingles = json.loads(fixture.read_text(encoding="utf-8"))

        self.session.add(
            TcgSet(
                abbr="SBSC",
                name="Speed Duel: Streets of Battle City",
                region="TCG",
            )
        )
        self.session.add(
            TcgSet(
                abbr="RA05",
                name="Rarity Collection 5",
                region="TCG",
            )
        )
        self.session.add(
            TcgSet(
                abbr="CONF",
                name="Conflict Set",
                region="TCG",
            )
        )
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _clear_default_sets(self):
        self.session.delete(self.session.get(TcgSet, "CONF"))
        self.session.delete(self.session.get(TcgSet, "RA05"))
        self.session.delete(self.session.get(TcgSet, "SBSC"))
        self.session.commit()

    def _seed_two_cards_for_set(self, abbr: str, *, card_id_start: int = 1) -> None:
        for offset, card_id in enumerate((card_id_start, card_id_start + 1)):
            self.session.add(Card(id=card_id, name=f"Test Card {card_id}"))
            self.session.add(
                Printing(
                    card_id=card_id,
                    set_code=f"{abbr}-EN00{offset + 1}",
                    set_rarity_code="C",
                )
            )
        self.session.commit()

    def _seed_named_cards_for_set(
        self,
        abbr: str,
        card_names: list[str],
        *,
        card_id_start: int = 1,
    ) -> None:
        for offset, card_name in enumerate(card_names):
            card_id = card_id_start + offset
            self.session.add(Card(id=card_id, name=card_name))
            self.session.add(
                Printing(
                    card_id=card_id,
                    set_code=f"{abbr}-EN{offset + 1:03d}",
                    set_rarity_code="C",
                )
            )
        self.session.commit()

    def test_maps_set_with_consistent_id_expansion(self):
        self.session.delete(self.session.get(TcgSet, "CONF"))
        self._seed_two_cards_for_set("SBSC", card_id_start=101)
        self._seed_two_cards_for_set("RA05", card_id_start=201)
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, self.nonsingles, upsert=False
        )
        self.assertEqual(mappings["SBSC"].expansion_id, 5316)
        self.assertEqual(mappings["RA05"].expansion_id, 6424)
        self.assertEqual(skipped, [])

    def test_rejects_conflicting_id_expansion(self):
        self.session.delete(self.session.get(TcgSet, "SBSC"))
        self.session.delete(self.session.get(TcgSet, "RA05"))
        self._seed_two_cards_for_set("CONF", card_id_start=301)
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, self.nonsingles, upsert=False
        )
        self.assertEqual(mappings, {})
        self.assertTrue(any(e["abbr"] == "CONF" for e in rejections))

    def test_ocg_nonsingle_products_are_ignored(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(
                abbr="ABYR",
                name="Abyss Rising",
                region="TCG",
            )
        )
        self._seed_two_cards_for_set("ABYR", card_id_start=401)
        self.session.commit()

        nonsingles = [
            {
                "idProduct": 1,
                "name": "Abyss Rising Booster",
                "idExpansion": 1419,
            },
            {
                "idProduct": 2,
                "name": "Abyss Rising Booster Box",
                "idExpansion": 1419,
            },
            {
                "idProduct": 3,
                "name": "Abyss Rising (OCG) Booster",
                "idExpansion": 4738,
            },
            {
                "idProduct": 4,
                "name": "Abyss Rising (OCG) Booster Box",
                "idExpansion": 4738,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["ABYR"].expansion_id, 1419)
        self.assertEqual(skipped, [])

    def test_japanese_nonsingle_products_are_ignored(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(
                abbr="ABPF",
                name="Absolute Powerforce",
                region="TCG",
            )
        )
        self._seed_two_cards_for_set("ABPF", card_id_start=501)
        self.session.commit()

        nonsingles = [
            {
                "idProduct": 1,
                "name": "Absolute Powerforce Booster",
                "idExpansion": 1187,
            },
            {
                "idProduct": 608124,
                "name": "Absolute Powerforce 2-Pack Set",
                "idExpansion": 4787,
            },
            {
                "idProduct": 608128,
                "name": "Absolute Powerforce (Japanese) Booster Box",
                "idExpansion": 4787,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["ABPF"].expansion_id, 1187)
        self.assertEqual(skipped, [])

    def test_skips_championship_prize_set(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(
                abbr="2011",
                name="Yu-Gi-Oh! World Championship 2011 prize cards",
                region="TCG",
            )
        )
        self.session.commit()

        nonsingles = [
            {
                "idProduct": 254574,
                "name": "World Championship 2011 Card Pack Booster",
                "idExpansion": 1368,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertNotIn("2011", mappings)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["abbr"], "2011")
        self.assertEqual(skipped[0]["reason"], "championship_prize_cards")

    def test_skips_championship_series_prize_set(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(
                abbr="25YC",
                name="Yu-Gi-Oh! Championship Series 2025 prize cards",
                region="TCG",
            )
        )
        self.session.commit()

        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, self.nonsingles, upsert=False
        )
        self.assertNotIn("25YC", mappings)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["reason"], "championship_prize_cards")

    def test_skips_world_championship_2023_prize_set(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(
                abbr="2023",
                name="Yu-Gi-Oh! World Championship 2023 prize cards",
                region="TCG",
            )
        )
        self.session.commit()

        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, self.nonsingles, upsert=False
        )
        self.assertNotIn("2023", mappings)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["reason"], "championship_prize_cards")

    def test_skips_participation_yugipedia_set(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(
                abbr="DL2",
                name="Duelist League Series 2 participation cards",
                region="TCG",
            )
        )
        self._seed_two_cards_for_set("DL2", card_id_start=701)
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, self.nonsingles, upsert=False
        )
        self.assertNotIn("DL2", mappings)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["abbr"], "DL2")
        self.assertEqual(skipped[0]["reason"], "promotional_or_participation_cards")

    def test_skips_promotional_yugipedia_set(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(
                abbr="DOD",
                name="Yu-Gi-Oh! The Dawn of Destiny promotional cards",
                region="TCG",
            )
        )
        self._seed_two_cards_for_set("DOD", card_id_start=801)
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, self.nonsingles, upsert=False
        )
        self.assertNotIn("DOD", mappings)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["abbr"], "DOD")
        self.assertEqual(skipped[0]["reason"], "promotional_or_participation_cards")

    def test_maps_advent_calendar_via_normalized_name(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(
                abbr="AC19",
                name="Yu-Gi-Oh! Advent Calendar (2019)",
                region="TCG",
            )
        )
        self._seed_two_cards_for_set("AC19", card_id_start=601)
        self.session.commit()

        nonsingles = [
            {
                "idProduct": 399139,
                "name": "Advent Calendar 2019",
                "idExpansion": 2664,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["AC19"].expansion_id, 2664)
        self.assertEqual(skipped, [])

    def test_structure_deck_name_helper(self):
        self.assertEqual(
            structure_deck_cardmarket_name("Machina Mayhem Structure Deck"),
            "Structure Deck: Machina Mayhem",
        )
        self.assertIsNone(structure_deck_cardmarket_name("Structure Deck: Sacred Beasts"))
        self.assertIsNone(structure_deck_cardmarket_name("Legend of Blue Eyes White Dragon"))
        self.assertIsNone(structure_deck_cardmarket_name("Starter Deck: Joey"))

    def test_maps_structure_deck_via_cardmarket_naming(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(
                abbr="SDMM",
                name="Machina Mayhem Structure Deck",
                region="TCG",
            )
        )
        self._seed_two_cards_for_set("SDMM", card_id_start=611)
        self.session.commit()

        nonsingles = [
            {
                "idProduct": 254271,
                "name": "Structure Deck: Machina Mayhem",
                "idExpansion": 1188,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["SDMM"].expansion_id, 1188)
        self.assertEqual(skipped, [])

    def test_structure_deck_colon_prefix_uses_primary_match(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(
                abbr="SDSB",
                name="Structure Deck: Sacred Beasts",
                region="TCG",
            )
        )
        self._seed_two_cards_for_set("SDSB", card_id_start=621)
        self.session.commit()

        nonsingles = [
            {
                "idProduct": 1,
                "name": "Structure Deck: Sacred Beasts",
                "idExpansion": 5001,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["SDSB"].expansion_id, 5001)
        self.assertEqual(skipped, [])

    def test_booster_sp_expansion_is_excluded(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="DESO", name="Destiny Soldiers", region="TCG"))
        self._seed_two_cards_for_set("DESO", card_id_start=631)
        nonsingles = [
            {"idProduct": 1, "name": "Destiny Soldiers Booster", "idExpansion": 1738},
            {
                "idProduct": 2,
                "name": "Booster SP: Destiny Soldiers Booster",
                "idExpansion": 4658,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(self.session, nonsingles, upsert=False)
        self.assertEqual(mappings["DESO"].expansion_id, 1738)

    def test_gold_series_2013_2014_expansion_is_excluded(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="GLD1", name="Gold Series", region="TCG"))
        self._seed_two_cards_for_set("GLD1", card_id_start=641)
        nonsingles = [
            {"idProduct": 1, "name": "Gold Series 1 Booster", "idExpansion": 1141},
            {"idProduct": 2, "name": "Gold Series 2013 Booster", "idExpansion": 4710},
            {"idProduct": 3, "name": "Gold Series 2014 Booster Box", "idExpansion": 4727},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(self.session, nonsingles, upsert=False)
        self.assertEqual(mappings["GLD1"].expansion_id, 1141)

    def test_gld1_maps_via_alias_only(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="GLD1", name="Gold Series", region="TCG"))
        self._seed_two_cards_for_set("GLD1", card_id_start=651)
        nonsingles = [
            {"idProduct": 1, "name": "Gold Series 1 Booster", "idExpansion": 1141},
            {"idProduct": 2, "name": "Gold Series 2 Booster", "idExpansion": 1163},
            {"idProduct": 3, "name": "Gold Series 3 Booster", "idExpansion": 1204},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(self.session, nonsingles, upsert=False)
        self.assertEqual(mappings["GLD1"].expansion_id, 1141)

    def test_ha01_does_not_match_hidden_arsenal_2(self):
        self.assertTrue(nonsingle_matches_alias("Hidden Arsenal Booster", "Hidden Arsenal"))
        self.assertFalse(nonsingle_matches_alias("Hidden Arsenal 2 Booster", "Hidden Arsenal"))
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="HA01", name="Hidden Arsenal", region="TCG"))
        self._seed_two_cards_for_set("HA01", card_id_start=661)
        nonsingles = [
            {"idProduct": 1, "name": "Hidden Arsenal Booster", "idExpansion": 1177},
            {"idProduct": 2, "name": "Hidden Arsenal 2 Booster", "idExpansion": 1201},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(self.session, nonsingles, upsert=False)
        self.assertEqual(mappings["HA01"].expansion_id, 1177)

    def test_ha05_maps_via_alias(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(abbr="HA05", name="Hidden Arsenal 5: Steelswarm Invasion", region="TCG")
        )
        self._seed_two_cards_for_set("HA05", card_id_start=671)
        nonsingles = [
            {"idProduct": 1, "name": "Hidden Arsenal 5 Booster", "idExpansion": 1284},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(self.session, nonsingles, upsert=False)
        self.assertEqual(mappings["HA05"].expansion_id, 1284)

    def test_lc02_maps_via_alias(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(
                abbr="LC02",
                name="Legendary Collection 2: The Duel Academy Years",
                region="TCG",
            )
        )
        self._seed_two_cards_for_set("LC02", card_id_start=681)
        nonsingles = [
            {"idProduct": 1, "name": "Legendary Collection 2", "idExpansion": 1335},
            {"idProduct": 2, "name": "Legendary Collection 3", "idExpansion": 1336},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(self.session, nonsingles, upsert=False)
        self.assertEqual(mappings["LC02"].expansion_id, 1335)

    def test_pevo_excludes_structure_deck_product(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="PEVO", name="Pendulum Evolution", region="TCG"))
        self._seed_two_cards_for_set("PEVO", card_id_start=691)
        nonsingles = [
            {"idProduct": 1, "name": "Pendulum Evolution Booster", "idExpansion": 1768},
            {
                "idProduct": 2,
                "name": "Structure Deck: Pendulum Evolution",
                "idExpansion": 4649,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(self.session, nonsingles, upsert=False)
        self.assertEqual(mappings["PEVO"].expansion_id, 1768)

    def test_skips_collectible_tin_set(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(
                abbr="CT09",
                name="Collectible Tins 2012 Wave 1",
                region="TCG",
            )
        )
        self.session.commit()

        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, self.nonsingles, upsert=False
        )
        self.assertNotIn("CT09", mappings)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["abbr"], "CT09")
        self.assertEqual(skipped[0]["reason"], "collectible_tins")

    def test_skips_set_with_one_card_without_error(self):
        self.session.delete(self.session.get(TcgSet, "CONF"))
        self.session.delete(self.session.get(TcgSet, "RA05"))
        self.session.delete(self.session.get(TcgSet, "SBSC"))
        self.session.add(
            TcgSet(
                abbr="2020",
                name="KC Grand Tournament prize card",
                region="TCG",
            )
        )
        self.session.add(Card(id=1, name="Test Card"))
        self.session.add(
            Printing(
                card_id=1,
                set_code="2020-EN001",
                set_rarity_code="ScR",
            )
        )
        self.session.commit()

        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, self.nonsingles, upsert=False
        )
        self.assertNotIn("2020", mappings)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["abbr"], "2020")
        self.assertEqual(skipped[0]["reason"], "insufficient_yugipedia_cards")

    def test_skips_zero_card_set_without_error(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(
                abbr="ABPF-TK",
                name="Absolute Powerforce Plus",
                region="TCG",
            )
        )
        self.session.commit()

        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, self.nonsingles, upsert=False
        )
        self.assertNotIn("ABPF-TK", mappings)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["abbr"], "ABPF-TK")
        self.assertEqual(skipped[0]["reason"], "insufficient_yugipedia_cards")

    def test_deck_build_pack_expansion_is_excluded(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="AMDE", name="Amazing Defenders", region="TCG"))
        self._seed_two_cards_for_set("AMDE", card_id_start=701)
        nonsingles = [
            {"idProduct": 1, "name": "Amazing Defenders Booster", "idExpansion": 5400},
            {"idProduct": 2, "name": "Deck Build Pack: Amazing Defenders Booster", "idExpansion": 5401},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(self.session, nonsingles, upsert=False)
        self.assertEqual(mappings["AMDE"].expansion_id, 5400)

    def test_korean_expansion_is_excluded(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="LOB", name="Legend of Blue Eyes White Dragon", region="TCG"))
        self._seed_two_cards_for_set("LOB", card_id_start=801)
        nonsingles = [
            {"idProduct": 1, "name": "Legend of Blue Eyes White Dragon Booster", "idExpansion": 1001},
            {"idProduct": 2, "name": "Legend of Blue Eyes White Dragon (Korean) Booster", "idExpansion": 2002},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(self.session, nonsingles, upsert=False)
        self.assertEqual(mappings["LOB"].expansion_id, 1001)

    def test_rush_duel_expansion_is_excluded(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(abbr="ANN5", name="5th Anniversary Pack", region="TCG")
        )
        self._seed_two_cards_for_set("ANN5", card_id_start=951)
        nonsingles = [
            {"idProduct": 1, "name": "5th Anniversary Pack Booster", "idExpansion": 3001},
            {
                "idProduct": 2,
                "name": "Rush Duel: 5th Anniversary Pack Booster",
                "idExpansion": 3002,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(self.session, nonsingles, upsert=False)
        self.assertEqual(mappings["ANN5"].expansion_id, 3001)

    def test_short_regional_bracket_code_is_excluded(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="LOB", name="Legend of Blue Eyes White Dragon", region="TCG"))
        self._seed_two_cards_for_set("LOB", card_id_start=961)
        nonsingles = [
            {"idProduct": 1, "name": "Legend of Blue Eyes White Dragon Booster", "idExpansion": 1001},
            {
                "idProduct": 2,
                "name": "Legend of Blue Eyes White Dragon (LDD) Booster",
                "idExpansion": 2002,
            },
            {
                "idProduct": 3,
                "name": "Legend of Blue Eyes White Dragon (LDD) Booster Box",
                "idExpansion": 2002,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(self.session, nonsingles, upsert=False)
        self.assertEqual(mappings["LOB"].expansion_id, 1001)

    def test_long_bracket_text_25th_anniversary_is_excluded(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="LOB", name="Legend of Blue Eyes White Dragon", region="TCG"))
        self._seed_two_cards_for_set("LOB", card_id_start=971)
        nonsingles = [
            {"idProduct": 1, "name": "Legend of Blue Eyes White Dragon Booster", "idExpansion": 1001},
            {
                "idProduct": 2,
                "name": (
                    "Legend of Blue Eyes White Dragon "
                    "(Legendary Collection: 25th Anniversary Edition) Booster"
                ),
                "idExpansion": 2002,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(self.session, nonsingles, upsert=False)
        self.assertEqual(mappings["LOB"].expansion_id, 1001)
        self.assertEqual(mappings["LOB"].expansion_ids, (1001,))

    def test_condition_marker_product_is_excluded(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="LOB", name="Legend of Blue Eyes White Dragon", region="TCG"))
        self._seed_two_cards_for_set("LOB", card_id_start=901)
        nonsingles = [
            {"idProduct": 1, "name": "Legend of Blue Eyes White Dragon Booster", "idExpansion": 1001},
            {"idProduct": 2, "name": "Legend of Blue Eyes White Dragon Booster (MI", "idExpansion": 2002},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(self.session, nonsingles, upsert=False)
        self.assertEqual(mappings["LOB"].expansion_id, 1001)

    def test_tp4_excludes_ots_and_speed_duel_products(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="TP4", name="Tournament Pack 4", region="TCG"))
        self._seed_two_cards_for_set("TP4", card_id_start=1001)
        nonsingles = [
            {"idProduct": 1, "name": "OTS Tournament Pack 4 Booster", "idExpansion": 1799},
            {"idProduct": 2, "name": "Tournament Pack 4 Booster", "idExpansion": 1100},
            {"idProduct": 3, "name": "Speed Duel Tournament Pack 4 Booster", "idExpansion": 5085},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(self.session, nonsingles, upsert=False)
        self.assertEqual(mappings["TP4"].expansion_id, 1100)

    def test_stp5_alias_matches_colon_style_cardmarket_name(self):
        alias = "Speed Duel: Tournament Pack 5 Booster"
        self.assertTrue(
            nonsingle_matches_alias("Speed Duel: Tournament Pack 5 Booster", alias)
        )
        self.assertFalse(
            nonsingle_matches_alias("Speed Duel: Tournament Pack 50 Booster", alias)
        )

    def test_stp5_maps_via_colon_style_alias(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(abbr="STP5", name="Speed Duel Tournament Pack 5", region="TCG")
        )
        self._seed_two_cards_for_set("STP5", card_id_start=1301)
        nonsingles = [
            {
                "idProduct": 1,
                "name": "Speed Duel: Tournament Pack 5 Booster",
                "idExpansion": 5247,
            },
            {
                "idProduct": 2,
                "name": "Speed Duel Tournament Pack 4 Booster",
                "idExpansion": 5085,
            },
            {"idProduct": 3, "name": "Tournament Pack 5 Booster", "idExpansion": 1082},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(self.session, nonsingles, upsert=False)
        self.assertEqual(mappings["STP5"].expansion_id, 5247)

    def test_stp6_maps_via_colon_style_alias(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(abbr="STP6", name="Speed Duel Tournament Pack 6", region="TCG")
        )
        self._seed_two_cards_for_set("STP6", card_id_start=1401)
        nonsingles = [
            {
                "idProduct": 1,
                "name": "Speed Duel: Tournament Pack 6 Booster",
                "idExpansion": 5397,
            },
            {
                "idProduct": 2,
                "name": "Speed Duel Tournament Pack 5 Booster",
                "idExpansion": 5247,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(self.session, nonsingles, upsert=False)
        self.assertEqual(mappings["STP6"].expansion_id, 5397)

    def test_tn23_resolves_to_tin_expansion_with_priced_singles(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(abbr="TN23", name="25th Anniversary Tin: Dueling Heroes", region="TCG")
        )
        self._seed_named_cards_for_set(
            "TN23",
            ["Dark Magician", "Blue-Eyes White Dragon"],
            card_id_start=1101,
        )
        nonsingles = [
            {"idProduct": 1, "name": "25th Anniversary Tin: Dueling Heroes", "idExpansion": 5337},
            {"idProduct": 2, "name": "25th Anniversary Tin: Dueling Heroes Mega Pack Booster", "idExpansion": 5465},
        ]
        singles = [
            {"idProduct": 5001, "name": "Dark Magician", "idCategory": 5, "idExpansion": 5337},
            {"idProduct": 5002, "name": "Blue-Eyes White Dragon", "idCategory": 5, "idExpansion": 5337},
        ]
        prices = [
            {"idProduct": 5001, "trend": 1.0, "avg": 1.0, "low": 0.5},
            {"idProduct": 5002, "trend": 2.0, "avg": 2.0, "low": 1.0},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session,
            nonsingles,
            singles=singles,
            price_rows=prices,
            upsert=False,
        )
        self.assertEqual(mappings["TN23"].expansion_id, 5337)

    def test_resolves_shared_card_with_complementary_prices(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="TINX", name="Tin Example Set", region="TCG"))
        self._seed_named_cards_for_set(
            "TINX",
            ["Shared Card", "Other Card"],
            card_id_start=1201,
        )
        nonsingles = [
            {"idProduct": 1, "name": "Tin Example Set", "idExpansion": 6001},
            {"idProduct": 2, "name": "Tin Example Set Mega Pack", "idExpansion": 6002},
        ]
        singles = [
            {"idProduct": 60001, "name": "Shared Card", "idCategory": 5, "idExpansion": 6001},
            {"idProduct": 60002, "name": "Shared Card", "idCategory": 5, "idExpansion": 6002},
            {"idProduct": 60003, "name": "Other Card", "idCategory": 5, "idExpansion": 6001},
            {"idProduct": 60004, "name": "Other Card", "idCategory": 5, "idExpansion": 6002},
        ]
        prices = [
            {"idProduct": 60001, "trend": 1.0, "avg": None, "low": None},
            {"idProduct": 60002, "trend": None, "avg": 1.5, "low": None},
            {"idProduct": 60003, "trend": 0.5, "avg": 0.5, "low": None},
            {"idProduct": 60004, "trend": 0.5, "avg": 0.5, "low": None},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session,
            nonsingles,
            singles=singles,
            price_rows=prices,
            upsert=False,
        )
        self.assertEqual(mappings["TINX"].expansion_ids, (6001, 6002))

    def test_raises_on_conflicting_prices_for_shared_card(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="TINX", name="Tin Example Set", region="TCG"))
        self._seed_named_cards_for_set(
            "TINX",
            ["Shared Card", "Other Card"],
            card_id_start=1301,
        )
        nonsingles = [
            {"idProduct": 1, "name": "Tin Example Set", "idExpansion": 7001},
            {"idProduct": 2, "name": "Tin Example Set Mega Pack", "idExpansion": 7002},
        ]
        singles = [
            {"idProduct": 70001, "name": "Shared Card", "idCategory": 5, "idExpansion": 7001},
            {"idProduct": 70002, "name": "Shared Card", "idCategory": 5, "idExpansion": 7002},
            {"idProduct": 70003, "name": "Other Card", "idCategory": 5, "idExpansion": 7001},
            {"idProduct": 70004, "name": "Other Card", "idCategory": 5, "idExpansion": 7002},
        ]
        prices = [
            {"idProduct": 70001, "trend": 1.0, "avg": 1.0, "low": 0.5},
            {"idProduct": 70002, "trend": 9.0, "avg": 9.0, "low": 8.0},
            {"idProduct": 70003, "trend": 0.5, "avg": 0.5, "low": None},
            {"idProduct": 70004, "trend": 0.5, "avg": 0.5, "low": None},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session,
            nonsingles,
            singles=singles,
            price_rows=prices,
            upsert=False,
        )
        self.assertNotIn("TINX", mappings)
        self.assertTrue(any(e["abbr"] == "TINX" for e in rejections))

    def test_excludes_sacred_beasts_of_chaos_products(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(abbr="SDSB", name="Structure Deck: Sacred Beasts", region="TCG")
        )
        self._seed_two_cards_for_set("SDSB", card_id_start=1401)
        nonsingles = [
            {
                "idProduct": 1,
                "name": "Structure Deck: Sacred Beasts",
                "idExpansion": 3133,
            },
            {
                "idProduct": 2,
                "name": "Structure Deck: Sacred Beasts of Chaos",
                "idExpansion": 4557,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["SDSB"].expansion_ids, (3133,))

    def test_excludes_promotional_participation_expansion(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="LOB", name="Legend of Blue Eyes White Dragon", region="TCG"))
        self._seed_two_cards_for_set("LOB", card_id_start=1501)
        nonsingles = [
            {"idProduct": 1, "name": "Legend of Blue Eyes White Dragon Booster", "idExpansion": 1001},
            {
                "idProduct": 2,
                "name": "Shonen Jump promotional cards Booster",
                "idExpansion": 2002,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(self.session, nonsingles, upsert=False)
        self.assertEqual(mappings["LOB"].expansion_ids, (1001,))

    def test_op01_number_boundary(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(abbr="OP01", name="OTS Tournament Pack 1", region="TCG")
        )
        self._seed_two_cards_for_set("OP01", card_id_start=1601)
        nonsingles = [
            {"idProduct": 1, "name": "OTS Tournament Pack 1 Booster", "idExpansion": 1699},
            {"idProduct": 2, "name": "OTS Tournament Pack 10 Booster", "idExpansion": 2454},
            {"idProduct": 3, "name": "OTS Tournament Pack 11 Booster", "idExpansion": 2542},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["OP01"].expansion_ids, (1699,))

    def test_ledu_parent_does_not_match_subseries(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="LEDU", name="Legendary Duelists", region="TCG"))
        self._seed_two_cards_for_set("LEDU", card_id_start=1701)
        nonsingles = [
            {"idProduct": 1, "name": "Legendary Duelists Booster", "idExpansion": 1817},
            {
                "idProduct": 2,
                "name": "Legendary Duelists: Ancient Millennium Booster",
                "idExpansion": 2048,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["LEDU"].expansion_ids, (1817,))

    def test_mago_does_not_match_mged(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="MAGO", name="Maximum Gold", region="TCG"))
        self._seed_two_cards_for_set("MAGO", card_id_start=1801)
        nonsingles = [
            {"idProduct": 1, "name": "Maximum Gold Booster", "idExpansion": 3339},
            {"idProduct": 2, "name": "Maximum Gold: El Dorado Booster", "idExpansion": 4371},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["MAGO"].expansion_ids, (3339,))

    def test_dark_revelation_volume_alias(self):
        self.assertEqual(
            dark_revelation_cardmarket_name("Dark Revelation Volume 4"),
            "Dark Revelation 4",
        )
        self._clear_default_sets()
        self.session.add(
            TcgSet(abbr="DR04", name="Dark Revelation Volume 4", region="TCG")
        )
        self._seed_two_cards_for_set("DR04", card_id_start=1901)
        nonsingles = [
            {"idProduct": 1, "name": "Dark Revelation 4 Booster", "idExpansion": 1143},
            {"idProduct": 2, "name": "Dark Revelation 3 Booster", "idExpansion": 1142},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["DR04"].expansion_ids, (1143,))

    def test_5ds_starter_deck_aliases(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(
                abbr="5DS1",
                name="Starter Deck: Yu-Gi-Oh! 5D's",
                region="TCG",
            )
        )
        self.session.add(
            TcgSet(
                abbr="5DS2",
                name="Starter Deck: Yu-Gi-Oh! 5D's 2009",
                region="TCG",
            )
        )
        self._seed_two_cards_for_set("5DS1", card_id_start=2001)
        self._seed_two_cards_for_set("5DS2", card_id_start=2010)
        nonsingles = [
            {"idProduct": 1, "name": "5D's Starter Deck 2008", "idExpansion": 1173},
            {"idProduct": 2, "name": "5D's Starter Deck 2009", "idExpansion": 1172},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["5DS1"].expansion_ids, (1173,))
        self.assertEqual(mappings["5DS2"].expansion_ids, (1172,))

    def test_drlg_series_aliases(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="DRLG", name="Dragons of Legend", region="TCG"))
        self.session.add(TcgSet(abbr="DRL2", name="Dragons of Legend 2", region="TCG"))
        self._seed_two_cards_for_set("DRLG", card_id_start=2101)
        self._seed_two_cards_for_set("DRL2", card_id_start=2110)
        nonsingles = [
            {"idProduct": 1, "name": "Dragons of Legend Booster", "idExpansion": 1479},
            {"idProduct": 2, "name": "Dragons of Legend 2 Booster", "idExpansion": 1656},
            {"idProduct": 3, "name": "Dragons of Legend: Unleashed Booster", "idExpansion": 1713},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["DRLG"].expansion_ids, (1479,))
        self.assertEqual(mappings["DRL2"].expansion_ids, (1656,))

    def test_duad_curly_apostrophe(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="DUAD", name="Duelist's Advance", region="TCG"))
        self._seed_two_cards_for_set("DUAD", card_id_start=2201)
        nonsingles = [
            {"idProduct": 1, "name": "Duelist\u2019s Advance Booster", "idExpansion": 6083},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["DUAD"].expansion_ids, (6083,))

    def test_legendary_duelists_subtitle_strip(self):
        self.assertEqual(
            legendary_duelists_subtitle_name(
                "Legendary Duelists: Duels From the Deep"
            ),
            "Duels From the Deep",
        )
        self._clear_default_sets()
        self.session.add(
            TcgSet(
                abbr="LED9",
                name="Legendary Duelists: Duels From the Deep",
                region="TCG",
            )
        )
        self._seed_two_cards_for_set("LED9", card_id_start=2301)
        nonsingles = [
            {
                "idProduct": 1,
                "name": "Duels From the Deep Booster",
                "idExpansion": 4471,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["LED9"].expansion_ids, (4471,))

    def test_merges_lc05_expansions(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(abbr="LC05", name="Legendary Collection 5D's", region="TCG")
        )
        self._seed_named_cards_for_set(
            "LC05",
            ["Stardust Dragon", "Black Rose Dragon"],
            card_id_start=2401,
        )
        nonsingles = [
            {
                "idProduct": 1,
                "name": "Legendary Collection 5D's: Mega Pack Booster",
                "idExpansion": 1507,
            },
            {
                "idProduct": 2,
                "name": "Legendary Collection 5D's: Promo Box",
                "idExpansion": 1508,
            },
        ]
        singles = [
            {"idProduct": 8001, "name": "Stardust Dragon", "idCategory": 5, "idExpansion": 1507},
            {"idProduct": 8002, "name": "Black Rose Dragon", "idCategory": 5, "idExpansion": 1508},
        ]
        prices = [
            {"idProduct": 8001, "trend": 1.0, "avg": 1.0, "low": 0.5},
            {"idProduct": 8002, "trend": 2.0, "avg": 2.0, "low": 1.0},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session,
            nonsingles,
            singles=singles,
            price_rows=prices,
            upsert=False,
        )
        self.assertEqual(mappings["LC05"].expansion_ids, (1507, 1508))

    def test_merges_disjoint_tin_expansions(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="CT11", name="2014 Mega-Tins", region="TCG"))
        self._seed_named_cards_for_set(
            "CT11",
            ["Bujintei Susanowo", "Brotherhood of the Fire Fist - Tiger King"],
            card_id_start=2501,
        )
        nonsingles = [
            {
                "idProduct": 1,
                "name": '2014 Mega-Tins: ""Bujintei Susanowo"" Tin',
                "idExpansion": 1497,
            },
            {
                "idProduct": 2,
                "name": "2014 Mega-Tins Mega-Pack Booster",
                "idExpansion": 1498,
            },
        ]
        singles = [
            {
                "idProduct": 9001,
                "name": "Bujintei Susanowo",
                "idCategory": 5,
                "idExpansion": 1497,
            },
            {
                "idProduct": 9002,
                "name": "Brotherhood of the Fire Fist - Tiger King",
                "idCategory": 5,
                "idExpansion": 1498,
            },
        ]
        prices = [
            {"idProduct": 9001, "trend": 1.0, "avg": 1.0, "low": 0.5},
            {"idProduct": 9002, "trend": 2.0, "avg": 2.0, "low": 1.0},
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session,
            nonsingles,
            singles=singles,
            price_rows=prices,
            upsert=False,
        )
        self.assertEqual(mappings["CT11"].expansion_ids, (1497, 1498))

    def test_merges_tin_expansions_with_overlapping_card_price_conflict(self):
        self._clear_default_sets()
        self.session.add(TcgSet(abbr="CT11", name="2014 Mega-Tins", region="TCG"))
        mega_pack_cards = [
            "Bujintei Susanowo",
            "Brotherhood of the Fire Fist - Tiger King",
            "Number 101: Silent Honor ARK",
            "Castell, the Skyblaster Musketeer",
            "Gagaga Cowboy",
        ]
        self._seed_named_cards_for_set("CT11", mega_pack_cards, card_id_start=2601)
        nonsingles = [
            {
                "idProduct": 1,
                "name": '2014 Mega-Tins: ""Bujintei Susanowo"" Tin',
                "idExpansion": 1497,
            },
            {
                "idProduct": 2,
                "name": "2014 Mega-Tins Mega-Pack Booster",
                "idExpansion": 1498,
            },
        ]
        singles = [
            {
                "idProduct": 9101,
                "name": "Bujintei Susanowo",
                "idCategory": 5,
                "idExpansion": 1497,
            },
            {
                "idProduct": 9102,
                "name": "Bujintei Susanowo",
                "idCategory": 5,
                "idExpansion": 1498,
            },
        ]
        prices = [
            {"idProduct": 9101, "trend": 1.0, "avg": 1.0, "low": 0.5},
            {"idProduct": 9102, "trend": 5.0, "avg": 5.0, "low": 4.0},
        ]
        product_id = 9200
        for card_name in mega_pack_cards[1:]:
            singles.append(
                {
                    "idProduct": product_id,
                    "name": card_name,
                    "idCategory": 5,
                    "idExpansion": 1498,
                }
            )
            prices.append(
                {"idProduct": product_id, "trend": 2.0, "avg": 2.0, "low": 1.0}
            )
            product_id += 1
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session,
            nonsingles,
            singles=singles,
            price_rows=prices,
            upsert=False,
        )
        self.assertEqual(mappings["CT11"].expansion_ids, (1497, 1498))
        counts = mappings["CT11"].expansion_match_counts
        self.assertIsNotNone(counts)
        self.assertGreater(counts[1498], counts[1497])

    def test_starter_deck_name_helper(self):
        self.assertEqual(
            starter_deck_cardmarket_name("Starter Deck: Yu-Gi-Oh! 5D's"),
            "5D's Starter Deck",
        )
        self.assertEqual(
            starter_deck_cardmarket_name("Starter Deck: Joey"),
            "Joey Starter Deck",
        )

    def test_non_sealed_does_not_exclude_expansion(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(abbr="SDJ", name="Starter Deck: Joey", region="TCG")
        )
        self._seed_two_cards_for_set("SDJ", card_id_start=3001)
        nonsingles = [
            {
                "idProduct": 248161,
                "name": "Starter Deck: Joey",
                "idExpansion": 1018,
            },
            {
                "idProduct": 883373,
                "name": "Starter Deck: Joey (non-sealed)",
                "idExpansion": 1018,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["SDJ"].expansion_id, 1018)
        self.assertEqual(skipped, [])

    def test_starter_deck_aliases_avoid_evolution_cross_match(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(abbr="SDK", name="Starter Deck: Kaiba", region="TCG")
        )
        self._seed_two_cards_for_set("SDK", card_id_start=3011)
        nonsingles = [
            {
                "idProduct": 254276,
                "name": "Starter Deck: Kaiba",
                "idExpansion": 1055,
            },
            {
                "idProduct": 254279,
                "name": "Starter Deck: Kaiba Evolution",
                "idExpansion": 1081,
            },
            {
                "idProduct": 265406,
                "name": "Starter Deck: Kaiba Reloaded",
                "idExpansion": 1467,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["SDK"].expansion_id, 1055)
        self.assertEqual(skipped, [])

    def test_lc06_maps_base_expansion_only(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(abbr="LC06", name="Legendary Collection Kaiba", region="TCG")
        )
        self._seed_two_cards_for_set("LC06", card_id_start=3021)
        nonsingles = [
            {
                "idProduct": 315136,
                "name": "Legendary Collection Kaiba Mega Pack Booster",
                "idExpansion": 2066,
            },
            {
                "idProduct": 315137,
                "name": "Legendary Collection Kaiba",
                "idExpansion": 2067,
            },
            {
                "idProduct": 841649,
                "name": "Legendary Collection Kaiba (2025 Reprint)",
                "idExpansion": 2067,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["LC06"].expansion_id, 2067)
        self.assertEqual(skipped, [])

    def test_sdws_structure_deck_r_alias(self):
        self._clear_default_sets()
        self.session.add(
            TcgSet(
                abbr="SDWS",
                name="Warriors' Strike Structure Deck",
                region="TCG",
            )
        )
        self._seed_two_cards_for_set("SDWS", card_id_start=3031)
        nonsingles = [
            {
                "idProduct": 607066,
                "name": "Structure Deck R: Warriors' Strike",
                "idExpansion": 4572,
            },
        ]
        mappings, skipped, rejections = map_expansions_from_nonsingles(
            self.session, nonsingles, upsert=False
        )
        self.assertEqual(mappings["SDWS"].expansion_id, 4572)
        self.assertEqual(skipped, [])


if __name__ == "__main__":
    unittest.main()
