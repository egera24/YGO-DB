"""Parse Yugipedia Card_Tips pages."""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

SKIP_H2_TITLES = frozenset({"navigation", "references", "list", "see also"})

_BOILERPLATE_SELECTORS = (
    ".navbox-wrapper",
    ".navbox",
    ".mobile-show",
    "table.card-query-main",
    "table.card-list",
    "table.smwtable",
    ".card-query-more-links",
    "[id^='nitro-content-banner']",
)


def _section_title(h2: Tag) -> str:
    headline = h2.find(class_="mw-headline")
    if headline:
        return headline.get_text(strip=True)
    return h2.get_text(strip=True)


def _strip_boilerplate(root: Tag) -> None:
    for selector in _BOILERPLATE_SELECTORS:
        for element in root.select(selector):
            element.decompose()


def _normalize_tip_text(text: str) -> str:
    return " ".join(text.split())


def _flatten_list_items(ul: Tag) -> list[str]:
    tips: list[str] = []
    for li in ul.find_all("li", recursive=False):
        nested = li.find("ul")
        direct_text = _normalize_tip_text(li.get_text(" ", strip=True))
        if nested and nested.get_text(strip=True):
            nested_text = nested.get_text(" ", strip=True)
            if direct_text.endswith(nested_text):
                direct_text = direct_text[: -len(nested_text)].strip()
            elif nested_text in direct_text:
                direct_text = direct_text.replace(nested_text, "", 1).strip()
        if direct_text:
            tips.append(direct_text)
        if nested:
            tips.extend(_flatten_list_items(nested))
    return tips


def _tips_before_first_h2(parser_output: Tag) -> list[str]:
    tips: list[str] = []
    for child in parser_output.children:
        if not getattr(child, "name", None):
            continue
        if child.name == "h2":
            break
        if child.name == "ul":
            tips.extend(_flatten_list_items(child))
    return tips


def _tips_until_next_h2(h2: Tag) -> list[str]:
    tips: list[str] = []
    for sibling in h2.find_next_siblings():
        if sibling.name == "h2":
            break
        if sibling.name == "ul":
            tips.extend(_flatten_list_items(sibling))
    return tips


def parse_tips_html(html: str) -> list[dict]:
    """Return format sections with flattened tip strings."""
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find(id="mw-content-text") or soup
    parser_output = content.find(class_="mw-parser-output") or content
    _strip_boilerplate(parser_output)

    sections: list[dict] = []

    pre_tips = _tips_before_first_h2(parser_output)
    if pre_tips:
        sections.append({"format": "", "tips": pre_tips})

    for h2 in parser_output.find_all("h2"):
        title = _section_title(h2)
        if not title or title.lower() in SKIP_H2_TITLES:
            continue
        tips = _tips_until_next_h2(h2)
        if tips:
            sections.append({"format": title, "tips": tips})

    return sections
