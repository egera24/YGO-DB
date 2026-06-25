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

EN_ROW = """
<tr><td>2023-04-20</td><td><a href="/wiki/LOB-EN062" title="LOB-EN062">LOB-EN062</a></td><td><a href="/wiki/LOB" title="LOB"><i>Legend of Blue Eyes White Dragon (25th Anniversary Edition)</i></a></td><td><a href="/wiki/Super_Rare" title="Super Rare">Super Rare</a></td></tr>
"""

NA_ROW = """
<tr><td>2002-03-08</td><td><a href="/wiki/LOB-001" title="LOB-001">LOB-001</a></td><td><a href="/wiki/LOB" title="LOB"><i>Legend of Blue Eyes White Dragon</i></a></td><td><a href="/wiki/Super_Rare" title="Super Rare">Super Rare</a></td></tr>
"""

EU_ROW = """
<tr><td>2015-05-28</td><td><a href="/wiki/YS15-END18" title="YS15-END18">YS15-END18</a></td><td><a href="/wiki/YS15" title="YS15"><i>2-Player Starter Deck: Yuya &amp; Declan</i></a></td><td><a href="/wiki/Common" title="Common">Common</a></td></tr>
"""

JA_ROW = """
<tr><td>2003-12-09</td><td><a href="/wiki/LOB-K062" title="LOB-K062">LOB-K062</a></td><td><a href="/wiki/LOB" title="LOB"><i>Legend of Blue Eyes White Dragon</i></a></td><td><a href="/wiki/Super_Rare" title="Super Rare">Super Rare</a></td></tr>
"""

FR_ROW = """
<tr><td>2003-03-01</td><td><a href="/wiki/LDD-F050" title="LDD-F050">LDD-F050</a></td><td><a href="/wiki/LOB" title="LOB"><i>Legend of Blue Eyes White Dragon</i></a></td><td><a href="/wiki/Super_Rare" title="Super Rare">Super Rare</a></td></tr>
"""

TABLE_TEMPLATE = """
<table id="cts--EN" class="wikitable sortable card-list cts">
<thead><tr><th>Release</th><th>Number</th><th>Set</th><th>Rarity</th></tr></thead>
<tbody>{rows}</tbody>
</table>
"""

MULTI_REGION_TEMPLATE = """
<table id="cts--EN" class="wikitable sortable card-list cts">
<thead><tr><th>Release</th><th>Number</th><th>Set</th><th>Rarity</th></tr></thead>
<tbody>{en_rows}</tbody>
</table>
<table id="cts--NA" class="wikitable sortable card-list cts">
<thead><tr><th>Release</th><th>Number</th><th>Set</th><th>Rarity</th></tr></thead>
<tbody>{na_rows}</tbody>
</table>
<table id="cts--EU" class="wikitable sortable card-list cts">
<thead><tr><th>Release</th><th>Number</th><th>Set</th><th>Rarity</th></tr></thead>
<tbody>{eu_rows}</tbody>
</table>
<table id="cts--JP" class="wikitable sortable card-list cts">
<thead><tr><th>Release</th><th>Number</th><th>Set</th><th>Rarity</th></tr></thead>
<tbody>{ja_rows}</tbody>
</table>
<table id="cts--FR" class="wikitable sortable card-list cts">
<thead><tr><th>Release</th><th>Number</th><th>Set</th><th>French name</th><th>Rarity</th></tr></thead>
<tbody>{fr_rows}</tbody>
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

    def test_all_english_tcg_regions(self):
        html = MULTI_REGION_TEMPLATE.format(
            en_rows=EN_ROW,
            na_rows=NA_ROW,
            eu_rows=EU_ROW,
            ja_rows=JA_ROW,
            fr_rows=FR_ROW,
        )
        soup = BeautifulSoup(html, "html.parser")
        sets = extract_card_sets(soup) or []
        codes = [s["set_code"] for s in sets]
        self.assertEqual(codes, ["LOB-EN062", "LOB-001", "YS15-END18"])
        self.assertNotIn("LOB-K062", codes)
        self.assertNotIn("LDD-F050", codes)


if __name__ == "__main__":
    unittest.main()
