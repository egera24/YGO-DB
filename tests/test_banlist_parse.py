"""Tests for Konami banlist JSON parsing."""

import unittest
from datetime import date

from ygo_app.banlist.parse import normalize_list_payload, parse_effective_date, format_banlist_label


class BanlistParseTests(unittest.TestCase):
    def test_parse_effective_date_dd_mm_yyyy(self):
        self.assertEqual(parse_effective_date("18/05/2026"), date(2026, 5, 18))

    def test_format_banlist_label_from_effective_date(self):
        self.assertEqual(format_banlist_label(date(2026, 5, 18), "18/05/2026"), "May 2026")

    def test_format_banlist_label_preserves_month_year(self):
        self.assertEqual(format_banlist_label(date(2026, 2, 2), "February 2026"), "February 2026")

    def test_normalize_list_payload(self):
        payload = {
            "from": "18/05/2026",
            "0": [{"nameeng": "Pot of Greed", "cid": 55144522}],
            "1": [{"nameeng": "Monster Reborn", "cid": 83764718}],
            "2": [{"nameeng": "Called by the Grave", "cid": 24224830}],
        }
        normalized = normalize_list_payload(
            payload, source_list_id="current", label="18/05/2026"
        )
        self.assertEqual(normalized["effective_from"], date(2026, 5, 18))
        self.assertEqual(normalized["label"], "May 2026")
        self.assertEqual(len(normalized["entries"]), 3)
        statuses = {entry["card_name_raw"]: entry["status"] for entry in normalized["entries"]}
        self.assertEqual(statuses["Pot of Greed"], "forbidden")
        self.assertEqual(statuses["Monster Reborn"], "limited")
        self.assertEqual(statuses["Called by the Grave"], "semi_limited")


if __name__ == "__main__":
    unittest.main()
