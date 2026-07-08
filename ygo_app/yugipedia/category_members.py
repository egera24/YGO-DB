"""Discover cards printed without a passcode via the MediaWiki categorymembers API.

The password-range ``ask`` query in :mod:`ygo_app.yugipedia.passcodes` can only
find cards that have a ``Password``. Cards printed without one (Egyptian Gods,
Tokens, some promos) are enumerated instead from the wiki category
``Category:Cards printed without a password``.

Each discovered member is emitted in the same shape as the passcode list so it
flows through the existing details scrape, but with ``password=""`` and
``passwordless=True`` so downstream stages can assign a surrogate id.
"""

from __future__ import annotations

import time

import requests

from ygo_app.yugipedia.constants import USER_AGENT

PASSWORDLESS_CATEGORY = "Category:Cards printed without a password"
API_URL = "https://yugipedia.com/api.php"
_MAIN_NAMESPACE = 0
_PAGE_LIMIT = 500
_MAX_PAGES = 50


def _wiki_url_from_title(title: str) -> str:
    return "https://yugipedia.com/wiki/" + title.replace(" ", "_")


def get_category_members(
    session: requests.Session,
    api_url: str = API_URL,
    *,
    category: str = PASSWORDLESS_CATEGORY,
) -> list[dict]:
    """Return every main-namespace page in ``category`` as passcode-list entries."""
    members: list[dict] = []
    seen_titles: set[str] = set()
    cmcontinue: str | None = None

    for _ in range(_MAX_PAGES):
        params = {
            "action": "query",
            "format": "json",
            "list": "categorymembers",
            "cmtitle": category,
            "cmnamespace": _MAIN_NAMESPACE,
            "cmlimit": _PAGE_LIMIT,
            "cmtype": "page",
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue

        try:
            response = session.get(api_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception as e:  # noqa: BLE001 - network best-effort, logged
            print(f"    Error fetching category members: {e}")
            break

        batch = data.get("query", {}).get("categorymembers", [])
        for page in batch:
            title = page.get("title")
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            members.append(
                {
                    "name": title,
                    "card_type": "",
                    "password": "",
                    "url": _wiki_url_from_title(title),
                    "passwordless": True,
                }
            )

        cmcontinue = data.get("continue", {}).get("cmcontinue")
        if not cmcontinue:
            break
        time.sleep(1)

    return members


def fetch_passwordless_cards() -> list[dict]:
    """Fetch all passwordless card entries from Yugipedia."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    print(f"\nFetching category: {PASSWORDLESS_CATEGORY}")
    members = get_category_members(session)
    print(f"  Found {len(members)} passwordless card pages")
    return members
