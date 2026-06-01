"""Fetch YGOProDeck card catalog from API (no local all_cards.json required)."""

from __future__ import annotations

import json

import requests

from ygo_app.config import YGO_API_URL


def fetch_card_entries() -> list[dict]:
    """Download full card list from YGOProDeck API."""
    print(f"Fetching catalog from {YGO_API_URL} ...")
    response = requests.get(YGO_API_URL, timeout=120)
    response.raise_for_status()
    payload = response.json()
    entries = payload.get("data", [])
    print(f"Received {len(entries)} cards from API.")
    return entries


def load_card_entries(path) -> list[dict]:
    """Load card list from a local JSON export file."""
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload.get("data", [])
