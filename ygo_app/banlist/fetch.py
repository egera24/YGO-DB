"""Fetch banlist JSON from Konami EU."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://www.yugioh-card.com/eu/_data/fllists"
USER_AGENT = "YGO-App-Catalog/1.0 (+https://github.com/)"


def fetch_json(path: str, *, timeout: int = 60) -> Any:
    url = f"{BASE_URL}/{path}"
    response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.json()


def fetch_options() -> dict[str, str]:
    return fetch_json("options.json")


def fetch_list(source_list_id: str) -> dict[str, Any]:
    if source_list_id == "current":
        return fetch_json("current.json")
    return fetch_json(f"{source_list_id}.json")


def load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
