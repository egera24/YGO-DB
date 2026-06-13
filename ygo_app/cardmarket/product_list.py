"""Scrape Cardmarket expansion product list pages."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ygo_app.cardmarket.constants import BASE_URL, DISCOVERY_MAX_RETRIES, FetchBackend
from ygo_app.cardmarket.http_client import RateLimiter, fetch_url
from ygo_app.yugipedia.scrape_progress import log_line


def _search_url(expansion_id: int, page: int) -> str:
    return (
        f"{BASE_URL}/en/YuGiOh/Products/Search?"
        f"searchMode=v1&idCategory=0&idExpansion={expansion_id}"
        f"&onlyAvailable=on&idRarity=0&site={page}"
    )


def _is_empty_first_page(html: str) -> bool:
    if "Sorry, no matches" in html:
        return True
    soup = BeautifulSoup(html, "html.parser")
    if soup.find("p", class_=re.compile(r"noResults")):
        return True
    return False


def _extract_card_number(row, card_name: str, row_text: str, parts: list[str]) -> str:
    card_number = ""
    for part in parts:
        if part == card_name:
            continue
        if re.match(r"^[A-Z0-9\-]{1,15}$", part, re.IGNORECASE):
            if part.isdigit() and int(part) > 100:
                continue
            if "€" in part or "," in part or "." in part:
                continue
            card_number = part
            break

    if not card_number:
        main_col = row.find("div", class_="col")
        if main_col:
            nested_row = main_col.find("div", class_="row")
            if nested_row:
                for col in nested_row.find_all("div", recursive=False):
                    col_classes = " ".join(col.get("class", []))
                    if "col-md-2" in col_classes and "d-lg-flex" in col_classes:
                        number_div = col.find("div")
                        if number_div:
                            text = number_div.get_text(strip=True)
                            if text and len(text) <= 20 and "€" not in text:
                                card_number = text
                                break
    return card_number


def extract_cards_from_html(
    html: str,
    *,
    expansion_id: int,
    expansion_name: str,
    expansion_code: str | None = None,
) -> tuple[list[dict], str | None]:
    cards: list[dict] = []
    soup = BeautifulSoup(html, "html.parser")
    exp_code = expansion_code

    for row in soup.find_all("div", id=re.compile(r"^productRow\d+")):
        try:
            row_id = row.get("id", "")
            match = re.search(r"productRow(\d+)", row_id)
            if not match:
                continue
            card_id = int(match.group(1))

            card_link = row.find("a", href=re.compile(r"/en/YuGiOh/Products/Singles/"))
            if not card_link:
                continue

            card_name = card_link.get_text(strip=True)
            href = card_link.get("href", "")
            card_url = href if href.startswith("http") else BASE_URL + href

            row_text = row.get_text(separator="|", strip=True)
            parts = [p.strip() for p in row_text.split("|") if p.strip()]
            card_number = _extract_card_number(row, card_name, row_text, parts)

            card_rarity = ""
            for svg in row.find_all("svg"):
                for attr in ("aria-label", "data-bs-original-title", "title"):
                    val = (svg.get(attr) or "").strip()
                    if val:
                        card_rarity = val
                        break
                if card_rarity:
                    break

            if not exp_code:
                exp_symbol = row.find("a", class_="expansion-symbol")
                if exp_symbol:
                    exp_span = exp_symbol.find("span")
                    if exp_span:
                        exp_code = exp_span.get_text().strip()

            cards.append(
                {
                    "expansion_id": expansion_id,
                    "expansion_name": expansion_name,
                    "expansion_code": exp_code or "",
                    "card_id": card_id,
                    "card_name": card_name,
                    "card_number": card_number,
                    "card_rarity": card_rarity,
                    "card_url": card_url,
                }
            )
        except Exception:
            continue

    return cards, exp_code


def probe_expansion_code(
    scraper,
    expansion_id: int,
    expansion_name: str,
    *,
    rate_limiter: RateLimiter,
    backend: FetchBackend = "cloudscraper",
) -> str | None:
    html, error = fetch_url(
        scraper,
        _search_url(expansion_id, 1),
        backend=backend,
        rate_limiter=rate_limiter,
        retries=DISCOVERY_MAX_RETRIES,
    )
    if not html:
        if error:
            log_line(
                f"[DISCOVER] probe expansion_id={expansion_id} "
                f"({expansion_name[:40]}) failed: {error}"
            )
        return None
    if _is_empty_first_page(html):
        return None
    _cards, exp_code = extract_cards_from_html(
        html,
        expansion_id=expansion_id,
        expansion_name=expansion_name,
    )
    return exp_code


def scrape_expansion_products(
    scraper,
    expansion_id: int,
    expansion_name: str,
    *,
    rate_limiter: RateLimiter,
    expansion_code: str | None = None,
    backend: FetchBackend = "cloudscraper",
) -> list[dict]:
    all_cards: list[dict] = []
    page = 1
    exp_code = expansion_code

    while True:
        html, error = fetch_url(
            scraper,
            _search_url(expansion_id, page),
            backend=backend,
            rate_limiter=rate_limiter,
            retries=DISCOVERY_MAX_RETRIES,
        )
        if not html:
            if page == 1:
                log_line(f"[DISCOVER] expansion {expansion_id} page 1 failed: {error}")
            break

        if page == 1 and _is_empty_first_page(html):
            break

        soup = BeautifulSoup(html, "html.parser")
        product_rows = soup.find_all("div", id=re.compile(r"^productRow\d+"))
        if not product_rows:
            break

        cards, exp_code = extract_cards_from_html(
            html,
            expansion_id=expansion_id,
            expansion_name=expansion_name,
            expansion_code=exp_code,
        )
        all_cards.extend(cards)
        page += 1

    return all_cards
