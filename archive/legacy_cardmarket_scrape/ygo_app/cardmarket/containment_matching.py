"""Containment-based Yugipedia set_code ↔ Cardmarket expansion/card_number matching."""

from __future__ import annotations

import re

from ygo_app.cardmarket.matching import normalize_rarity_label
from ygo_app.yugipedia.constants import RARITY_CODES

_RARITY_LABEL_BY_CODE = {code: label for label, code in RARITY_CODES.items()}


def normalize_base(code: str) -> str:
    return (code or "").strip().upper().replace("_", "-")


def normalize_suffix(text: str) -> str:
    """Normalize collector suffix for containment compare (strip leading zeros on digits)."""
    s = (text or "").strip().upper()
    if not s:
        return s
    if s.isdigit():
        return s.lstrip("0") or "0"
    # Alphanumeric like D18 — strip leading zeros from trailing digit run only
    match = re.match(r"^([A-Z]*?)0*(\d+)$", s)
    if match and match.group(1):
        return f"{match.group(1)}{match.group(2)}"
    return s


def parse_yugipedia_set_code(set_code: str) -> tuple[str, str] | None:
    """Return (base_expansion, collector_suffix) from Yugipedia set_code."""
    code = (set_code or "").strip().upper()
    if "-" not in code:
        return None
    base, rest = code.split("-", 1)
    if not base or not rest:
        return None
    for prefix in ("EN", "E", "A", "FR", "DE", "IT", "SP", "PT"):
        if rest.startswith(prefix) and len(rest) > len(prefix):
            rest = rest[len(prefix) :]
            break
    return base, rest


def expansion_contains(yugipedia_base: str, cardmarket_code: str) -> bool:
    yb = normalize_base(yugipedia_base)
    cm = normalize_base(cardmarket_code)
    if not yb or not cm:
        return False
    return yb in cm or cm.startswith(yb)


def number_contains(yugipedia_suffix: str, cardmarket_number: str) -> bool:
    ys = normalize_suffix(yugipedia_suffix)
    cm = normalize_suffix(cardmarket_number)
    if not ys or not cm:
        return False
    return cm in ys or ys.endswith(cm) or ys == cm


def cardmarket_matches_printing(
    *,
    cm_expansion_code: str,
    cm_card_number: str,
    cm_rarity: str,
    yugipedia_set_code: str,
    yugipedia_rarity_name: str | None = None,
    yugipedia_rarity_code: str | None = None,
) -> bool:
    parsed = parse_yugipedia_set_code(yugipedia_set_code)
    if not parsed:
        return False
    yg_base, yg_suffix = parsed
    if not expansion_contains(yg_base, cm_expansion_code):
        return False
    if not number_contains(yg_suffix, cm_card_number):
        return False
    cm_r = normalize_rarity_label(cm_rarity)
    yg_r = normalize_rarity_label(yugipedia_rarity_name, yugipedia_rarity_code)
    return cm_r == yg_r


def find_cardmarket_matches(
    cm_row: dict,
    *,
    set_code: str,
    rarity_name: str | None,
    rarity_code: str | None,
) -> bool:
    exp = cm_row.get("expansion_data") or cm_row
    card = cm_row.get("card_data") or cm_row
    return cardmarket_matches_printing(
        cm_expansion_code=str(exp.get("expansion_code") or ""),
        cm_card_number=str(card.get("card_number") or ""),
        cm_rarity=str(card.get("card_rarity") or ""),
        yugipedia_set_code=set_code,
        yugipedia_rarity_name=rarity_name,
        yugipedia_rarity_code=rarity_code,
    )


def match_printings_to_cardmarket(
    catalog: list[tuple[str, str, str | None]],
    details: list[dict],
) -> tuple[dict[tuple[str, str], dict], list[dict]]:
    """
    Match Yugipedia printings to Cardmarket detail rows.

    Returns (matches keyed by (set_code, rarity_code), ambiguity conflicts).
  Each printing may match 0 or 1 CM row; >1 CM per printing is a conflict.
    """
    matches: dict[tuple[str, str], dict] = {}
    conflicts: list[dict] = []

    for set_code, rarity_code, rarity_name in catalog:
        key = (set_code, rarity_code)
        hits: list[dict] = []
        for detail in details:
            if find_cardmarket_matches(
                detail,
                set_code=set_code,
                rarity_name=rarity_name,
                rarity_code=rarity_code,
            ):
                hits.append(detail)

        if len(hits) > 1:
            conflicts.append(
                {
                    "type": "ambiguous_yugipedia_match",
                    "set_code": set_code,
                    "rarity_code": rarity_code,
                    "cardmarket_product_ids": [
                        (h.get("card_data") or h).get("card_id") for h in hits
                    ],
                }
            )
        elif len(hits) == 1:
            matches[key] = hits[0]

    return matches, conflicts
