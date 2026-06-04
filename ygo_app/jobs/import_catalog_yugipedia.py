"""Import catalog from Yugipedia scrape JSON into the database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ygo_app.import_data import import_cards_entries
from ygo_app.yugipedia.card_import import yugipedia_entries_to_import
from ygo_app.yugipedia.paths import ALL_CARDS_PATH


def load_yugipedia_cards(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    if isinstance(data, list):
        return data
    raise ValueError(f"Unexpected JSON shape in {path}")


def resolve_min_cards(*, limit: int | None, min_cards: int | None) -> int:
    """Default safety floor: 1000 full catalog; 80% of limit for test imports."""
    if min_cards is not None:
        return min_cards
    if limit is not None:
        return max(1, int(limit * 0.8))
    return 1000


def import_from_yugipedia_json(
    path: Path,
    *,
    limit: int | None = None,
    min_cards: int | None = None,
) -> tuple[int, int]:
    entries = load_yugipedia_cards(path)
    api_entries = yugipedia_entries_to_import(entries)
    min_required = resolve_min_cards(limit=limit, min_cards=min_cards)
    if len(api_entries) < min_required:
        raise RuntimeError(
            f"Only {len(api_entries)} cards after mapping (minimum {min_required}). "
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
        default=None,
        help="Abort if fewer cards mapped than this (default: 1000, or 80%% of --limit)",
    )
    args = parser.parse_args(argv)

    if args.limit is not None and args.limit < 1:
        print("--limit must be >= 1", file=sys.stderr)
        return 1
    if args.min_cards is not None and args.min_cards < 1:
        print("--min-cards must be >= 1", file=sys.stderr)
        return 1

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
