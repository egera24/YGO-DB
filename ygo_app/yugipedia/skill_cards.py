"""Discover Skill Cards via the MediaWiki SMW ask API.

Physical Skill Cards are not covered by the ``Concept:CG cards`` passcode-range
query or ``Category:Cards printed without a password``. They are enumerated from
the same Special:Ask query used on Yugipedia's Skill Card list page.
"""

from __future__ import annotations

import time

import requests

from ygo_app.yugipedia.constants import USER_AGENT

API_URL = "https://yugipedia.com/api.php"
SKILL_CARDS_ASK_BASE = (
    "<q>[[Card type::Skill Card]] OR [[Page type::Skill page]]</q>"
    "[[Card type::Skill Card]]"
    "|?English name|?Card type|?Password|?Character|?Property"
)
_BATCH_LIMIT = 500


def _printout_text(values: list) -> str:
    """Return the first SMW printout as plain text."""
    if not values:
        return ""
    first = values[0]
    if isinstance(first, dict):
        return str(first.get("fulltext", "") or "")
    return str(first)


def _card_entry_from_ask_result(page_name: str, page_data: dict) -> dict | None:
    printouts = page_data.get("printouts", {})
    english_names = printouts.get("English name", [])
    card_name = english_names[0] if english_names else page_name
    if isinstance(card_name, dict):
        card_name = card_name.get("fulltext", page_name)

    card_type = _printout_text(printouts.get("Card type", [])) or "Skill Card"

    passwords = printouts.get("Password", [])
    password = str(passwords[0]) if passwords else ""
    if password:
        password = password.zfill(8)

    card_url = page_data.get("fullurl", "")
    if not card_url:
        card_url = "https://yugipedia.com/wiki/" + page_name.replace(" ", "_")

    entry: dict = {
        "name": card_name,
        "card_type": card_type,
        "password": password,
        "url": card_url,
    }

    character = _printout_text(printouts.get("Character", []))
    if character:
        entry["character"] = character

    property_val = _printout_text(printouts.get("Property", []))
    if property_val:
        entry["property"] = property_val

    if not password:
        entry["passwordless"] = True

    return entry


def get_skill_cards_in_batch(
    session: requests.Session,
    api_url: str,
    *,
    offset: int,
    limit: int = _BATCH_LIMIT,
) -> list[dict]:
    """Fetch one page of Skill Card ask results."""
    params = {
        "action": "ask",
        "format": "json",
        "query": (
            f"{SKILL_CARDS_ASK_BASE}|limit={limit}|offset={offset}|sort=#|order=asc"
        ),
    }
    response = session.get(api_url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if "query" not in data or "results" not in data["query"]:
        return []

    cards: list[dict] = []
    for page_name, page_data in data["query"]["results"].items():
        try:
            entry = _card_entry_from_ask_result(page_name, page_data)
            if entry is not None:
                cards.append(entry)
        except Exception:
            continue
    return cards


def fetch_skill_cards() -> list[dict]:
    """Fetch all Skill Card entries from Yugipedia."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    print("\nFetching Skill Cards (SMW ask)")
    all_cards: list[dict] = []
    offset = 0

    while True:
        batch = get_skill_cards_in_batch(session, API_URL, offset=offset)
        print(f"  Offset {offset}: Found {len(batch)} skill cards")
        if not batch:
            break
        all_cards.extend(batch)
        if len(batch) < _BATCH_LIMIT:
            break
        offset += _BATCH_LIMIT
        time.sleep(1)

    print(f"  Found {len(all_cards)} skill card pages total")
    return all_cards
