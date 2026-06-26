"""Validation for Cardmarket job-2 card list rows and expansion slices."""

from __future__ import annotations

import re
from typing import Any

SINGLES_URL_RE = re.compile(
    r"^https?://(www\.)?cardmarket\.com/en/YuGiOh/Products/Singles/",
    re.IGNORECASE,
)

REQUIRED_CARD_KEYS = (
    "expansion_seq",
    "expansion_id",
    "expansion_name",
    "expansion_code",
    "card_id",
    "card_name",
    "card_number",
    "card_rarity",
    "card_url",
)


class CardListValidationError(ValueError):
    """Invalid card list row or expansion slice."""


def validate_card_row(card: dict[str, Any]) -> None:
    for key in REQUIRED_CARD_KEYS:
        if key not in card:
            raise CardListValidationError(f"Missing required field {key!r}")
        if not str(card.get(key, "")).strip() and key != "expansion_code":
            raise CardListValidationError(f"Empty required field {key!r}")
    url = str(card["card_url"]).strip()
    if not SINGLES_URL_RE.match(url):
        raise CardListValidationError(f"Invalid card_url: {url!r}")
    if int(card["expansion_seq"]) < 1:
        raise CardListValidationError(f"Invalid expansion_seq: {card['expansion_seq']!r}")


def validate_expansion_slice(
    cards: list[dict[str, Any]],
    *,
    expansion: dict[str, Any],
    known_card_ids: set[int] | None = None,
) -> None:
    """Validate scraped cards for one expansion before commit."""
    seq = int(expansion["seq"])
    exp_id = int(expansion["expansion_id"])
    seen_in_slice: set[int] = set()
    known = known_card_ids or set()

    for card in cards:
        validate_card_row(card)
        if int(card["expansion_seq"]) != seq:
            raise CardListValidationError(
                f"expansion_seq mismatch: expected {seq}, got {card['expansion_seq']}"
            )
        if int(card["expansion_id"]) != exp_id:
            raise CardListValidationError(
                f"expansion_id mismatch: expected {exp_id}, got {card['expansion_id']}"
            )
        cid = int(card["card_id"])
        if cid in seen_in_slice:
            raise CardListValidationError(f"Duplicate card_id in expansion slice: {cid}")
        if cid in known:
            raise CardListValidationError(f"Duplicate card_id globally: {cid}")
        seen_in_slice.add(cid)
