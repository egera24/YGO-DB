"""Fetch and parse Yugipedia errata/tips supplements for catalog cards."""

from __future__ import annotations

import json
from pathlib import Path

from ygo_app.yugipedia.constants import SUPPLEMENT_PROBE_RETRIES, SUPPLEMENT_PROBE_TIMEOUT
from ygo_app.yugipedia.errata import (
    compute_errata_flags,
    filter_errata_by_language,
    parse_errata_html,
)
from ygo_app.yugipedia.http_client import fetch_page
from ygo_app.yugipedia.paths import ALL_CARDS_PATH, SET_CHRONOLOGY_PATH
from ygo_app.yugipedia.related_links import (
    errata_url_for_card_name,
    is_missing_supplement_page_error,
    tips_url_for_card_name,
)
from ygo_app.yugipedia.tips import parse_tips_html


def _load_json_list(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_set_release_lookup(path: Path = SET_CHRONOLOGY_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    rows = _load_json_list(path)
    lookup: dict[str, str] = {}
    for row in rows:
        abbr = row.get("abbr")
        release = row.get("release_date")
        if abbr and release:
            lookup[str(abbr).upper()] = release
    return lookup


def supplement_page_url(
    card: dict,
    field: str,
    name: str,
    builder,
) -> str | None:
    """Return stored link from detail scrape, or legacy canonical URL if key absent."""
    if field in card:
        return card.get(field)
    return builder(name)


def fetch_supplement_html(session, url: str) -> tuple[str | None, str | None]:
    """Fetch errata/tips page; short timeout, no retry loop for missing pages."""
    return fetch_page(
        session,
        url,
        retries=SUPPLEMENT_PROBE_RETRIES,
        timeout=SUPPLEMENT_PROBE_TIMEOUT,
    )


def supplements_complete(card: dict) -> bool:
    """True when errata and tips keys are present (scraped, possibly empty)."""
    return "errata" in card and "tips" in card


def apply_supplements_to_card(
    session,
    card: dict,
    *,
    set_release_lookup: dict[str, str],
    scrape_errata: bool = True,
    scrape_tips: bool = True,
) -> tuple[dict, str | None]:
    """
    Fetch errata/tips pages when URLs exist; return merged card fields and error.

    On success error is None. On hard failure returns partial update and error string.
    """
    name = card.get("name") or ""
    update: dict = {}

    if scrape_errata:
        errata_url = supplement_page_url(card, "errata_url", name, errata_url_for_card_name)
        if not errata_url:
            update["errata"] = []
            update["has_errata"] = False
        else:
            html, error = fetch_supplement_html(session, errata_url)
            if html and "card-errata" in html:
                versions = filter_errata_by_language(
                    parse_errata_html(html, set_release_lookup=set_release_lookup)
                )
                if versions:
                    update["errata"] = versions
                    has_errata, last_date = compute_errata_flags(versions)
                    update["has_errata"] = has_errata
                    if last_date:
                        update["last_erratum_date"] = last_date
                    else:
                        update["has_errata"] = len(versions) > 1 or any(
                            v.get("version_index", 0) > 0 for v in versions
                        )
                else:
                    update["errata"] = []
                    update["has_errata"] = False
            elif error and not is_missing_supplement_page_error(error):
                return update, error
            else:
                update["errata"] = []
                update["has_errata"] = False

    if scrape_tips:
        tips_url = supplement_page_url(card, "tips_url", name, tips_url_for_card_name)
        if not tips_url:
            update["tips"] = []
        else:
            html, error = fetch_supplement_html(session, tips_url)
            if html and 'id="mw-content-text"' in html:
                update["tips"] = parse_tips_html(html)
            elif error and not is_missing_supplement_page_error(error):
                return update, error
            else:
                update["tips"] = []

    return update, None
