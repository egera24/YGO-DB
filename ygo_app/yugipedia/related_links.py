"""Parse related-page links (Errata, Tips) from Yugipedia card pages."""

from __future__ import annotations

from urllib.parse import urljoin, unquote

from bs4 import BeautifulSoup, Tag

YUGIPEDIA_BASE = "https://yugipedia.com"


def _is_redlink(anchor: Tag) -> bool:
    href = anchor.get("href") or ""
    if "redlink=1" in href:
        return True
    title = anchor.get("title") or ""
    if "page does not exist" in title.lower():
        return True
    span = anchor.find("span")
    if span and span.get("style"):
        style = span.get("style", "").replace(" ", "").lower()
        if "#ba0000" in style:
            return True
    return False


def _normalize_wiki_url(href: str) -> str | None:
    if not href or href.startswith("#"):
        return None
    if href.startswith("http"):
        return href.split("#")[0]
    return urljoin(YUGIPEDIA_BASE, href.split("#")[0])


def _link_label(anchor: Tag) -> str:
    return anchor.get_text(strip=True)


def extract_related_links(soup: BeautifulSoup) -> dict[str, str | None]:
    """Return errata_url and tips_url when pages exist (not redlinks)."""
    out: dict[str, str | None] = {"errata_url": None, "tips_url": None}
    for anchor in soup.select("div.hlist a[href]"):
        if _is_redlink(anchor):
            continue
        label = _link_label(anchor)
        url = _normalize_wiki_url(anchor["href"])
        if not url:
            continue
        if label == "Errata":
            out["errata_url"] = url
        elif label == "Tips":
            out["tips_url"] = url
    return out


def errata_url_for_card_name(name: str) -> str:
    """Build canonical Card_Errata page URL from card name."""
    from urllib.parse import quote

    page = f"Card_Errata:{name.replace(' ', '_')}"
    return f"{YUGIPEDIA_BASE}/wiki/{quote(page.replace(' ', '_'), safe=':')}"


def tips_url_for_card_name(name: str) -> str:
    from urllib.parse import quote

    page = f"Card_Tips:{name.replace(' ', '_')}"
    return f"{YUGIPEDIA_BASE}/wiki/{quote(page.replace(' ', '_'), safe=':')}"


def card_name_from_wiki_url(url: str) -> str | None:
    """Extract card name from a Card_Errata:/Card_Tips: wiki URL."""
    if "/wiki/" not in url:
        return None
    page = unquote(url.split("/wiki/", 1)[1])
    for prefix in ("Card_Errata:", "Card_Tips:"):
        if page.startswith(prefix):
            return page[len(prefix) :].replace("_", " ")
    return None


def is_supplement_wiki_url(url: str) -> bool:
    """True for Card_Errata: / Card_Tips: wiki pages."""
    return "Card_Errata:" in url or "Card_Tips:" in url


def is_missing_supplement_page_error(error: str | None) -> bool:
    """True when Yugipedia has no errata/tips page (404 or hang/timeout)."""
    if not error:
        return False
    if "404" in error:
        return True
    lower = error.lower()
    return any(
        marker in lower
        for marker in (
            "readtimeout",
            "connecttimeout",
            "connection timed out",
            "read timed out",
        )
    )
