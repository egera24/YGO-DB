"""Extract English TCG card set / printing rows from Yugipedia card pages."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ygo_app.yugipedia.constants import RARITY_CODES

# Yugipedia Card Timeline Set table suffixes for English TCG regions
# (see Module:Data/static/region/data on yugipedia.com).
ENGLISH_TCG_CTS_SUFFIXES = frozenset({"EN", "NA", "EU", "AU", "OC"})


def _is_english_tcg_set_table(table_id: str | None) -> bool:
    """True if table id is cts--{EN|NA|EU|AU|OC} (English TCG, not OCG/other languages)."""
    if not table_id or not table_id.startswith("cts--"):
        return False
    suffix = table_id[5:].split("-", 1)[0]
    return suffix in ENGLISH_TCG_CTS_SUFFIXES


def rarity_code_for(rarity_name: str) -> str:
    """Return short rarity code, or empty string if unknown (import uses full label)."""
    return RARITY_CODES.get(rarity_name.strip(), "")


def extract_rarities_from_cell(rarity_cell: Tag) -> list[str]:
    """Collect all rarity labels from a set-table rarity cell (supports multiple <br>)."""
    seen: set[str] = set()
    rarities: list[str] = []
    for link in rarity_cell.find_all("a"):
        text = link.get_text(strip=True)
        if text and text not in seen:
            seen.add(text)
            rarities.append(text)
    if rarities:
        return rarities
    text = rarity_cell.get_text(strip=True)
    if text:
        return [text]
    return []


def extract_card_sets(soup: BeautifulSoup) -> list[dict] | None:
    """Extract card sets from all English TCG card-timeline-set tables."""
    card_sets: list[dict] = []
    for table in soup.find_all("table", class_="card-list"):
        if not _is_english_tcg_set_table(table.get("id")):
            continue
        tbody = table.find("tbody")
        if not tbody:
            continue
        for row in tbody.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            release_date = cells[0].get_text(strip=True)
            set_code = cells[1].get_text(strip=True)
            set_name = cells[2].get_text(strip=True)
            set_name = re.sub(r"<.*?>", "", set_name)
            for rarity in extract_rarities_from_cell(cells[3]):
                card_sets.append(
                    {
                        "set_name": set_name,
                        "set_code": set_code,
                        "set_rarity": rarity,
                        "set_rarity_code": rarity_code_for(rarity),
                        "set_release_date": release_date,
                    }
                )
    return card_sets if card_sets else None
