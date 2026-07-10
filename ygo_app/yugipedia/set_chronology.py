"""Parse Yugipedia Set chronology page into TCG set metadata."""

from __future__ import annotations

import re
from typing import Iterator

from bs4 import BeautifulSoup, Tag

from ygo_app.yugipedia.date_parse import date_to_iso, parse_yugipedia_date

SET_CHRONOLOGY_URL = "https://yugipedia.com/wiki/Set_chronology"
TCG_SECTION_ID = "TCG"


def _headline_text(tag: Tag | None) -> str:
    if tag is None:
        return ""
    headline = tag.find(class_="mw-headline")
    if headline:
        return headline.get_text(strip=True)
    return tag.get_text(strip=True)


def _cell_text(cell: Tag) -> str:
    return cell.get_text(" ", strip=True)


def _find_tcg_h2(soup: BeautifulSoup) -> Tag | None:
    headline = soup.find(id=TCG_SECTION_ID)
    if headline is None:
        return soup.find("h2", id=TCG_SECTION_ID)
    if headline.name == "h2":
        return headline
    return headline.find_parent("h2")


def _iter_tcg_blocks(soup: BeautifulSoup) -> Iterator[tuple[str, Tag]]:
    """Yield (series_name, table) pairs under the TCG h2 section."""
    tcg_h2 = _find_tcg_h2(soup)
    if tcg_h2 is None:
        return

    series = ""
    for sibling in tcg_h2.find_all_next():
        if sibling.name == "h2":
            break
        if sibling.name == "h3":
            series = _headline_text(sibling)
            continue
        if sibling.name == "table" and "wikitable" in (sibling.get("class") or []):
            yield series, sibling


def _parse_table_row(row: Tag, *, series: str, region: str) -> dict | None:
    cells = row.find_all("td")
    if len(cells) < 4:
        return None
    abbr = _cell_text(cells[0])
    if not abbr or abbr == "Abbr.":
        return None
    name = _cell_text(cells[1])
    set_type = _cell_text(cells[2])
    release_raw = _cell_text(cells[3])
    release_date = parse_yugipedia_date(release_raw)
    return {
        "abbr": abbr,
        "name": name,
        "set_type": set_type,
        "series": series,
        "region": region,
        "release_date": date_to_iso(release_date),
        "release_date_raw": release_raw if release_date is None else None,
    }


def _merge_set_chronology_row(existing: dict, new: dict) -> None:
    """Combine duplicate abbr rows, preferring parseable release dates."""
    existing_date = existing.get("release_date")
    new_date = new.get("release_date")
    if existing_date is None and new_date is not None:
        existing["release_date"] = new_date
        existing["release_date_raw"] = None
    elif existing_date and new_date and new_date < existing_date:
        existing["release_date"] = new_date


def parse_set_chronology_html(html: str, *, region: str = "TCG") -> list[dict]:
    """Extract set rows from Set chronology HTML."""
    soup = BeautifulSoup(html, "html.parser")
    by_abbr: dict[str, dict] = {}

    for series, table in _iter_tcg_blocks(soup):
        tbody = table.find("tbody")
        if not tbody:
            continue
        for row in tbody.find_all("tr"):
            parsed = _parse_table_row(row, series=series, region=region)
            if not parsed:
                continue
            abbr = parsed["abbr"]
            existing = by_abbr.get(abbr)
            if existing is None:
                by_abbr[abbr] = parsed
            else:
                _merge_set_chronology_row(existing, parsed)
    return list(by_abbr.values())


def set_abbr_from_code(set_code: str | None) -> str | None:
    """Extract expansion abbr from a printing code like ABYR-EN084."""
    if not set_code:
        return None
    match = re.match(r"^([A-Za-z0-9]+)-", set_code.strip())
    return match.group(1).upper() if match else None
