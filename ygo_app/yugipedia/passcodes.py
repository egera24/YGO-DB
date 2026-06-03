"""Fetch Yugipedia passcode index via MediaWiki API (password ranges)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from ygo_app.yugipedia.constants import PASSWORD_RANGES, USER_AGENT
from ygo_app.yugipedia.paths import PASSCODE_LIST_PATH, ensure_catalog_dir


def get_cards_in_password_range(
    session: requests.Session,
    api_url: str,
    password_start: int,
    password_end: int,
) -> list[dict]:
    cards: list[dict] = []
    offset = 0
    limit = 500
    max_offset = 5000

    print(f"\n  Querying password range: {password_start:08d} - {password_end:08d}")

    while offset < max_offset:
        params = {
            "action": "ask",
            "format": "json",
            "query": (
                f"[[Concept:CG cards]][[Password::≥{password_start}]]"
                f"[[Password::≤{password_end}]]"
                f"|?English name|?Card type|?Password"
                f"|limit={limit}|offset={offset}|sort=Password|order=asc"
            ),
        }
        try:
            response = session.get(api_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if "query" not in data or "results" not in data["query"]:
                break

            results = data["query"]["results"]
            if not results:
                break

            cards_in_batch = 0
            for page_name, page_data in results.items():
                try:
                    printouts = page_data.get("printouts", {})
                    english_names = printouts.get("English name", [])
                    card_name = english_names[0] if english_names else page_name

                    card_types = printouts.get("Card type", [])
                    if card_types:
                        if isinstance(card_types[0], dict):
                            card_type = card_types[0].get("fulltext", "")
                        else:
                            card_type = str(card_types[0])
                    else:
                        card_type = ""

                    passwords = printouts.get("Password", [])
                    password = str(passwords[0]) if passwords else ""
                    if password:
                        password = password.zfill(8)
                    else:
                        continue

                    card_url = page_data.get("fullurl", "")
                    if not card_url:
                        card_name_encoded = page_name.replace(" ", "_")
                        card_url = f"https://yugipedia.com/wiki/{card_name_encoded}"

                    cards.append(
                        {
                            "name": card_name,
                            "card_type": card_type,
                            "password": password,
                            "url": card_url,
                        }
                    )
                    cards_in_batch += 1
                except Exception:
                    continue

            print(f"    Offset {offset}: Found {cards_in_batch} cards")
            if cards_in_batch < limit:
                break
            offset += limit
            time.sleep(1)
        except Exception as e:
            print(f"    Error at offset {offset}: {e}")
            break

    return cards


def fetch_all_passcodes() -> list[dict]:
    api_url = "https://yugipedia.com/api.php"
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    all_cards: list[dict] = []
    seen_passwords: set[str] = set()

    for range_num, (start, end) in enumerate(PASSWORD_RANGES, 1):
        print(f"\nRange {range_num}/{len(PASSWORD_RANGES)}: {start:08d} - {end:08d}")
        range_cards = get_cards_in_password_range(session, api_url, start, end)
        new_cards = 0
        for card in range_cards:
            if card["password"] not in seen_passwords:
                all_cards.append(card)
                seen_passwords.add(card["password"])
                new_cards += 1
        print(f"  Added {new_cards} unique cards (total {len(all_cards)})")
        if range_num < len(PASSWORD_RANGES):
            time.sleep(5)

    return all_cards


def save_passcode_list(cards: list[dict], path: Path | None = None) -> Path:
    ensure_catalog_dir()
    out = path or PASSCODE_LIST_PATH
    with out.open("w", encoding="utf-8") as f:
        json.dump(cards, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(cards)} cards to {out}")
    return out


def run_passcode_scrape(*, output_path: Path | None = None) -> Path:
    print("=" * 70)
    print(" Yugipedia passcode list scrape")
    print("=" * 70)
    cards = fetch_all_passcodes()
    if not cards:
        raise RuntimeError("No cards fetched from Yugipedia API")
    return save_passcode_list(cards, output_path)
