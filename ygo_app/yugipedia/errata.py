"""Parse Yugipedia Card_Errata pages."""

from __future__ import annotations

import html as html_module
import re

from bs4 import BeautifulSoup, NavigableString, Tag

from ygo_app.yugipedia.set_chronology import set_abbr_from_code

_ALLOWED_LORE_TAGS = frozenset({"del", "ins", "b", "i", "br"})


def _headline_language(h2: Tag) -> str:
    headline = h2.find(class_="mw-headline")
    if headline:
        return headline.get_text(strip=True)
    return h2.get_text(strip=True)


def _serialize_lore_node(node) -> str:
    if isinstance(node, NavigableString):
        return html_module.escape(str(node))
    if not isinstance(node, Tag):
        return ""
    name = node.name
    if name == "br":
        return "<br>"
    if name in _ALLOWED_LORE_TAGS:
        inner = "".join(_serialize_lore_node(child) for child in node.children)
        return f"<{name}>{inner}</{name}>"
    return "".join(_serialize_lore_node(child) for child in node.children)


def _lore_html_from_cell(cell: Tag | None) -> str:
    if not cell:
        return ""
    return "".join(_serialize_lore_node(child) for child in cell.children).strip()


def _lore_text_from_node(node) -> str:
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    if node.name == "br":
        return "\n"
    if node.name == "del":
        return "".join(
            _lore_text_from_node(child)
            for child in node.children
            if isinstance(child, Tag) and child.name == "ins"
        )
    return "".join(_lore_text_from_node(child) for child in node.children)


def _lore_text_from_cell(cell: Tag | None) -> str:
    if not cell:
        return ""
    raw = _lore_text_from_node(cell)
    lines: list[str] = []
    for line in raw.split("\n"):
        normalized = re.sub(r"[^\S\n]+", " ", line).strip()
        if normalized:
            lines.append(normalized)
    return "\n".join(lines)


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
        if re.match(r"^[A-Z0-9]+-[A-Z0-9]+$", text):
            set_code = text
        elif not set_name:
            set_name = text
    return set_code, set_name


def _is_header_row(tr: Tag) -> bool:
    return bool(tr.find_all("th")) and not tr.find_all("td")


def _parse_errata_table(
    table: Tag,
    *,
    language: str,
    set_release_lookup: dict[str, str] | None = None,
) -> list[dict]:
    set_release_lookup = set_release_lookup or {}
    versions: list[dict] = []
    pending_headers: list[str] = []

    for tr in table.find_all("tr"):
        if _is_header_row(tr):
            pending_headers = [th.get_text(strip=True) for th in tr.find_all("th")]
            continue

        row_class = tr.get("class") or []
        if "lores" not in row_class or not pending_headers:
            continue

        images_tr = tr.find_next_sibling(
            "tr", class_=lambda c: c and "images" in c
        )
        lore_cells = tr.find_all("td")
        image_cells = images_tr.find_all("td") if images_tr else []

        for idx, header in enumerate(pending_headers):
            lore_cell = lore_cells[idx] if idx < len(lore_cells) else None
            image_cell = image_cells[idx] if idx < len(image_cells) else None
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
                    "version_index": len(versions),
                    "version_label": header,
                    "lore_text": _lore_text_from_cell(lore_cell),
                    "lore_html": _lore_html_from_cell(lore_cell),
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
