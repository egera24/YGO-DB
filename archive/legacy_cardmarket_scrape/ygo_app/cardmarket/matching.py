"""Match Yugipedia printings to Cardmarket product list rows."""

from __future__ import annotations

import re

from ygo_app.yugipedia.constants import RARITY_CODES

# Yugipedia set_code → Cardmarket card_set_number
_SET_CODE_EN = re.compile(r"^(.+?)-EN(.+)$", re.IGNORECASE)
_SET_CODE_LEGACY = re.compile(r"^([A-Z0-9]+)-(\d+)$", re.IGNORECASE)

_RARITY_LABEL_BY_CODE = {code: label for label, code in RARITY_CODES.items()}


def parse_set_code(set_code: str) -> tuple[str, str] | None:
    """Return (expansion_code, card_number) or None."""
    code = (set_code or "").strip()
    if not code:
        return None

    match = _SET_CODE_EN.match(code)
    if match:
        return match.group(1).upper(), match.group(2).upper()

    match = _SET_CODE_LEGACY.match(code)
    if match:
        return match.group(1).upper(), match.group(2).upper()

    return None


def normalized_set_number(set_code: str) -> str | None:
    parsed = parse_set_code(set_code)
    if not parsed:
        return None
    expansion_code, card_number = parsed
    return f"{expansion_code}-EN{card_number}"


def expansion_prefix(set_code: str) -> str | None:
    parsed = parse_set_code(set_code)
    if not parsed:
        return None
    return parsed[0]


def normalize_rarity_label(
    rarity_name: str | None = None,
    rarity_code: str | None = None,
) -> str:
    """Normalize to Cardmarket-style rarity label for matching."""
    if rarity_name and rarity_name.strip():
        return rarity_name.strip().lower()
    if rarity_code and rarity_code.strip():
        label = _RARITY_LABEL_BY_CODE.get(rarity_code.strip())
        if label:
            return label.lower()
        return rarity_code.strip().lower()
    return ""


def printing_match_key(set_code: str, rarity_name: str | None, rarity_code: str | None) -> tuple[str, str] | None:
    set_number = normalized_set_number(set_code)
    if not set_number:
        return None
    rarity = normalize_rarity_label(rarity_name, rarity_code)
    if not rarity:
        return None
    return (set_number.upper(), rarity)


def cardmarket_match_key(expansion_code: str, card_number: str, card_rarity: str) -> tuple[str, str]:
    set_number = f"{expansion_code.strip().upper()}-EN{card_number.strip().upper()}"
    return (set_number, (card_rarity or "").strip().lower())


def build_cardmarket_index(
    products: list[dict],
) -> dict[tuple[str, str], dict]:
    """Index Cardmarket list rows by (set_number, rarity)."""
    index: dict[tuple[str, str], dict] = {}
    for product in products:
        exp_code = (product.get("expansion_code") or "").strip()
        card_number = (product.get("card_number") or "").strip()
        card_rarity = (product.get("card_rarity") or "").strip()
        if not exp_code or not card_number or not card_rarity:
            continue
        key = cardmarket_match_key(exp_code, card_number, card_rarity)
        index[key] = product
    return index
