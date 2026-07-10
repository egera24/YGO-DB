"""Load distinct catalog printings for Cardmarket scrape (JSON or DB)."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from ygo_app.cardmarket.market_prices import distinct_catalog_printings


def load_yugipedia_entries(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    if isinstance(data, list):
        return data
    raise ValueError(f"Unexpected JSON shape in {path}")


def catalog_printings_from_yugipedia(path: Path) -> list[tuple[str, str, str | None]]:
    """Distinct (set_code, rarity_code, rarity_name) from Yugipedia scrape JSON."""
    entries = load_yugipedia_entries(path)
    out: list[tuple[str, str, str | None]] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        for cs in entry.get("card_sets") or []:
            set_code = (cs.get("set_code") or "").strip()
            rarity_code = (cs.get("set_rarity_code") or "").strip()
            rarity_name = cs.get("set_rarity")
            if not set_code or not rarity_code:
                continue
            key = (set_code, rarity_code)
            if key in seen:
                continue
            seen.add(key)
            out.append((set_code, rarity_code, rarity_name))
    return out


def load_catalog_printings(
  session: Session | None,
  *,
  catalog_path: Path | None = None,
) -> list[tuple[str, str, str | None]]:
    if catalog_path is not None:
        return catalog_printings_from_yugipedia(catalog_path)
    if session is None:
        raise ValueError("Either catalog_path or session is required")
    return distinct_catalog_printings(session)
