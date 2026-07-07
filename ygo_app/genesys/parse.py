"""Parse Genesys point list pages from Yugipedia HTML."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from bs4 import BeautifulSoup

POINT_LIST_TITLE_RE = re.compile(r"^(.+)_Point_List$")
POINT_LIST_PAGE_RE = re.compile(r"/wiki/([^?#]+_Point_List)")
# Only real article pages: /wiki/<Title>_Point_List with no namespace colon
# (namespaces such as Talk:, Special:, Category: all contain a colon).
RELATED_POINT_LIST_RE = re.compile(r"^/wiki/[^:?#]+_Point_List$")


def page_title_from_url(url: str) -> str:
    match = POINT_LIST_PAGE_RE.search(url)
    if not match:
        return ""
    return unquote(match.group(1).replace("_", " "))


def parse_effective_date_from_title(title: str) -> date | None:
    text = title.replace(" Point List", "").strip()
    for fmt in ("%B %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def clean_card_name(cell_text: str, link_title: str | None = None) -> str:
    if link_title:
        return link_title.strip()
    text = cell_text.strip().strip('"').strip("'").strip()
    return text


def parse_point_list_html(html: str, *, source_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    title = page_title_from_url(source_url) or (soup.title.string if soup.title else "")
    label = title.replace(" Point List", "").strip() or title
    effective_from = parse_effective_date_from_title(title) or date.today()

    entries: list[dict[str, Any]] = []
    for table in soup.select("table.wikitable"):
        headers = [th.get_text(strip=True).lower() for th in table.select("thead th")]
        if "card" not in headers or "cost" not in headers:
            continue
        card_idx = headers.index("card")
        cost_idx = headers.index("cost")
        for row in table.select("tbody tr"):
            cells = row.find_all("td")
            if len(cells) <= max(card_idx, cost_idx):
                continue
            card_cell = cells[card_idx]
            link = card_cell.find("a", title=True)
            card_name = clean_card_name(card_cell.get_text(), link.get("title") if link else None)
            cost_text = cells[cost_idx].get_text(strip=True).replace(",", "")
            if not card_name or not cost_text.isdigit():
                continue
            entries.append({"card_name_raw": card_name, "points": int(cost_text)})

    related_urls: set[str] = set()
    for anchor in soup.select("a[href*='_Point_List']"):
        href = anchor.get("href") or ""
        if href.startswith("https://yugipedia.com"):
            href = href[len("https://yugipedia.com"):]
        path = href.split("?")[0].split("#")[0]
        if RELATED_POINT_LIST_RE.match(path):
            related_urls.add(f"https://yugipedia.com{path}")

    return {
        "label": label,
        "effective_from": effective_from,
        "source_url": source_url.split("?")[0],
        "entries": entries,
        "related_urls": sorted(related_urls),
    }


def parse_point_list_file(path: Path, *, source_url: str) -> dict[str, Any]:
    return parse_point_list_html(path.read_text(encoding="utf-8", errors="replace"), source_url=source_url)
