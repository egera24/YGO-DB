"""Tests for multi-rarity card set extraction from Yugipedia HTML."""

import unittest

from bs4 import BeautifulSoup

from ygo_app.yugipedia.card_sets import extract_card_sets, extract_rarities_from_cell


RA03_ROW = """
<tr><td>2024-11-07</td><td><a href="/wiki/RA03-EN172" class="mw-redirect" title="RA03-EN172">RA03-EN172</a></td><td><a href="/wiki/Quarter_Century_Bonanza" title="Quarter Century Bonanza"><i>Quarter Century Bonanza</i></a></td><td><a href="/wiki/Platinum_Secret_Rare" title="Platinum Secret Rare">Platinum Secret Rare</a><br/><a href="/wiki/Quarter_Century_Secret_Rare" title="Quarter Century Secret Rare">Quarter Century Secret Rare</a></td></tr>
"""

DUAL_RARITY_SPELL_ROW = """
<tr><td>2025-07-31</td><td><a href="/wiki/JUSH-EN040" title="JUSH-EN040">JUSH-EN040</a></td><td><a href="/wiki/Justice_Hunters" title="Justice Hunters"><i>Justice Hunters</i></a></td><td><a href="/wiki/Super_Rare" title="Super Rare">Super Rare</a><br><a href="/wiki/Starlight_Rare" title="Starlight Rare">Starlight Rare</a></td></tr>
"""

TABLE_TEMPLATE = """
<table id="cts--EN" class="wikitable sortable card-list cts">
<thead><tr><th>Release</th><th>Number</th><th>Set</th><th>Rarity</th></tr></thead>
<tbody>{rows}</tbody>
</table>
"""


class TestExtractRarities(unittest.TestCase):
    def test_br_slash_multi_rarity(self):
        soup = BeautifulSoup(RA03_ROW, "html.parser")
        cell = soup.find("td", string=lambda _: False) or soup.find_all("td")[-1]
        # last td is rarity
        cells = soup.find("tr").find_all("td")
        rarities = extract_rarities_from_cell(cells[3])
        self.assertEqual(
            rarities,
            ["Platinum Secret Rare", "Quarter Century Secret Rare"],
        )

    def test_br_multi_rarity_spell(self):
        soup = BeautifulSoup(DUAL_RARITY_SPELL_ROW, "html.parser")
        cells = soup.find("tr").find_all("td")
        rarities = extract_rarities_from_cell(cells[3])
        self.assertEqual(rarities, ["Super Rare", "Starlight Rare"])


class TestExtractCardSets(unittest.TestCase):
    def _sets_from_rows(self, *rows: str) -> list[dict]:
        html = TABLE_TEMPLATE.format(rows="".join(rows))
        soup = BeautifulSoup(html, "html.parser")
        return extract_card_sets(soup) or []

    def test_ra03_two_printings_same_set_code(self):
        sets = self._sets_from_rows(RA03_ROW)
        codes = [s["set_code"] for s in sets]
        self.assertEqual(codes, ["RA03-EN172", "RA03-EN172"])
        rarities = {s["set_rarity"] for s in sets}
        self.assertEqual(
            rarities,
            {"Platinum Secret Rare", "Quarter Century Secret Rare"},
        )
        self.assertEqual(sets[0]["set_rarity_code"], "PScR")
        self.assertEqual(sets[1]["set_rarity_code"], "QCR")

    def test_dual_rarity_spell(self):
        sets = self._sets_from_rows(DUAL_RARITY_SPELL_ROW)
        self.assertEqual(len(sets), 2)
        self.assertEqual(sets[0]["set_code"], "JUSH-EN040")
        self.assertEqual(sets[1]["set_code"], "JUSH-EN040")
        self.assertEqual({s["set_rarity"] for s in sets}, {"Super Rare", "Starlight Rare"})


if __name__ == "__main__":
    unittest.main()
