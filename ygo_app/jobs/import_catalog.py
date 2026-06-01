"""Render Job entrypoint: import shared card catalog from YGOProDeck API."""

import sys

from ygo_app.import_data import import_cards_from_api


def main() -> int:
    cards, printings = import_cards_from_api()
    print(f"Catalog import complete: {cards} cards, {printings} printings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
