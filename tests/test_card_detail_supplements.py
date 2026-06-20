"""Tests for card detail errata/tips API helpers."""

import json
import unittest
from datetime import date

from ygo_app.models import Card, CardErrataVersion
from ygo_app.yugipedia.card_detail_extras import card_errata_for_api, card_tips_for_api
from ygo_app.yugipedia.card_import import _tips_json


class TestCardDetailExtras(unittest.TestCase):
    def test_errata_english_only(self):
        card = Card(
            id=84893333,
            name="Abyss Dweller",
            has_errata=True,
            last_erratum_date=date(2019, 10, 11),
        )
        card.errata_versions = [
            CardErrataVersion(
                card_id=84893333,
                language="English",
                version_index=0,
                version_label="Original",
                lore_text="Original text",
                set_code="ABYR-EN084",
                set_name="Abyss Rising",
                release_date=date(2012, 7, 21),
            ),
            CardErrataVersion(
                card_id=84893333,
                language="English",
                version_index=1,
                version_label="First erratum",
                lore_text="Updated text",
                set_code="DUDE-EN016",
                set_name="Duel Devastator",
                release_date=date(2019, 10, 11),
            ),
            CardErrataVersion(
                card_id=84893333,
                language="French",
                version_index=0,
                version_label="Original",
                lore_text="Texte",
            ),
        ]
        out = card_errata_for_api(card)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1].version_label, "First erratum")
        self.assertIn("Card_Errata", out[0].source_url or "")

    def test_errata_japanese_only_returns_empty(self):
        card = Card(
            id=12345678,
            name="Test Card",
            has_errata=True,
            last_erratum_date=date(2019, 10, 11),
        )
        card.errata_versions = [
            CardErrataVersion(
                card_id=12345678,
                language="Japanese",
                version_index=0,
                version_label="Original",
                lore_text="日本語",
            ),
            CardErrataVersion(
                card_id=12345678,
                language="Japanese",
                version_index=1,
                version_label="First erratum",
                lore_text="更新",
            ),
        ]
        self.assertEqual(card_errata_for_api(card), [])

    def test_tips_json_empty_list_is_none(self):
        self.assertIsNone(_tips_json({"tips": []}))
        self.assertIsNone(_tips_json({"tips": None}))

    def test_tips_json(self):
        card = Card(
            id=1,
            name="Test",
            tips=json.dumps(
                [
                    {
                        "format": "Traditional Format",
                        "tips": ["Tip one", "Tip two"],
                    }
                ]
            ),
        )
        sections = card_tips_for_api(card)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].format, "Traditional Format")
        self.assertEqual(sections[0].tips, ["Tip one", "Tip two"])


if __name__ == "__main__":
    unittest.main()
