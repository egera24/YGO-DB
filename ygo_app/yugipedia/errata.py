"""Parse Yugipedia Card_Errata pages."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag

from ygo_app.yugipedia.date_parse import date_to_iso
from ygo_app.yugipedia.set_chronology import set_abbr_from_code


def _headline_language(h2: Tag) -> str:
    headline = h2.find(class_="mw-headline")
    if headline:
        return headline.get_text(strip=True)
    return h2.get_text(strip=True)


def _lore_text_from_cell(cell: Tag) -> str:
    parts: list[str] = []
    for child in cell.children:
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if text:
                parts.append(text)
        elif child.name == "br":
            if parts and parts[-1]:
                parts.append("")
        elif child.name in ("del",):
            continue
        elif child.name in ("ins", "b", "i", "a", "span"):
            text = child.get_text(strip=True)
            if text:
                parts.append(text)
        else:
            text = child.get_text(strip=True)
            if text:
                parts.append(text)
    text = "\n".join(line for line in parts if line is not None)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _printing_from_image_cell(cell: Tag) -> tuple[str | None, str | None]:
    caption = cell.find(class_="thumbcaption")
    if not caption:
        return None, None
    links = caption.find_all("a", href=True)
    set_code = None
    set_name = None
    for link in links:
        href = link.get("href", "")
        text = link.get_text(strip=True)
        if not text:
            continue
        if "/wiki/File:" in href:
            continue
        if re.match(r"^[A-Z0-9]+-[A-Z]{2}\d+", text):
            set_code = text
        elif not set_name:
            set_name = text
    return set_code, set_name


def _parse_errata_table(
    table: Tag,
    *,
    language: str,
    set_release_lookup: dict[str, str] | None = None,
) -> list[dict]:
    set_release_lookup = set_release_lookup or {}
    thead = table.find("tr")
    if not thead:
        return []
    headers = [th.get_text(strip=True) for th in thead.find_all("th")]
    if not headers:
        return []

    lores_row = table.find("tr", class_="lores")
    images_row = table.find("tr", class_="images")
    if not lores_row:
        return []

    lore_cells = lores_row.find_all("td")
    image_cells = images_row.find_all("td") if images_row else []

    versions: list[dict] = []
    for idx, header in enumerate(headers):
        lore_cell = lore_cells[idx] if idx < len(lore_cells) else None
        image_cell = image_cells[idx] if idx < len(image_cells) else None
        lore_text = _lore_text_from_cell(lore_cell) if lore_cell else ""
        set_code, set_name = (
            _printing_from_image_cell(image_cell) if image_cell else (None, None)
        )
        release_date = None
        abbr = set_abbr_from_code(set_code)
        if abbr and abbr in set_release_lookup:
            release_date = set_release_lookup[abbr]
        versions.append(
            {
                "language": language,
                "version_index": idx,
                "version_label": header,
                "lore_text": lore_text,
                "set_code": set_code,
                "set_name": set_name,
                "release_date": release_date,
            }
        )
    return versions


def parse_errata_html(
    html: str,
    *,
    set_release_lookup: dict[str, str] | None = None,
) -> list[dict]:
    """Parse all language sections from a Card_Errata page."""
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find(id="mw-content-text") or soup
    versions: list[dict] = []

    for h2 in content.find_all("h2"):
        language = _headline_language(h2)
        if not language:
            continue
        table = h2.find_next("table", class_=lambda c: c and "card-errata" in c)
        if table is None:
            continue
        next_h2 = h2.find_next_sibling("h2")
        if table and next_h2 and table.sourceline and next_h2.sourceline:
            pass
        versions.extend(
            _parse_errata_table(
                table,
                language=language,
                set_release_lookup=set_release_lookup,
            )
        )
    return versions


def compute_errata_flags(versions: list[dict], *, language: str = "English") -> tuple[bool, str | None]:
    """Return has_errata and last_erratum_date ISO for the given language."""
    lang_versions = [v for v in versions if v.get("language") == language]
    if not lang_versions:
        lang_versions = versions
    if len(lang_versions) < 2:
        return False, None
    erratum_dates = [
        v["release_date"]
        for v in lang_versions
        if v.get("version_index", 0) > 0 and v.get("release_date")
    ]
    if not erratum_dates:
        return True, None
    return True, max(erratum_dates)
