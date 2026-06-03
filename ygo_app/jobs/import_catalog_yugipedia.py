"""Import catalog from Yugipedia scrape JSON into the database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ygo_app.import_data import import_cards_entries
from ygo_app.yugipedia.adapter import yugipedia_entries_to_api
from ygo_app.yugipedia.paths import ALL_CARDS_PATH


def load_yugipedia_cards(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    if isinstance(data, list):
        return data
    raise ValueError(f"Unexpected JSON shape in {path}")


def import_from_yugipedia_json(
    path: Path,
    *,
    limit: int | None = None,
    min_cards: int = 1000,
) -> tuple[int, int]:
    entries = load_yugipedia_cards(path)
    api_entries = yugipedia_entries_to_api(entries)
    if len(api_entries) < min_cards:
        raise RuntimeError(
            f"Only {len(api_entries)} cards after mapping (minimum {min_cards}). "
            "Scrape may have failed."
        )
    return import_cards_entries(api_entries, limit=limit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import Yugipedia catalog JSON to DB")
    parser.add_argument(
        "--json",
        type=Path,
        default=ALL_CARDS_PATH,
        help="Path to yugipedia_all_cards.json",
    )
    parser.add_argument("--limit", type=int, default=None, help="Import only N cards (testing)")
    parser.add_argument(
        "--min-cards",
        type=int,
        default=1000,
        help="Abort if fewer cards mapped than this (safety)",
    )
    args = parser.parse_args(argv)

    if not args.json.exists():
        print(f"Catalog file not found: {args.json}", file=sys.stderr)
        return 1

    cards, printings = import_from_yugipedia_json(
        args.json, limit=args.limit, min_cards=args.min_cards
    )
    print(f"Catalog import complete: {cards} cards, {printings} printings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
