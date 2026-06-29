"""Text normalization helpers for catalog matching."""

from __future__ import annotations

import re
import unicodedata

LINE_QUALIFIERS = ("speed duel", "ots", "structure deck")

NON_TCG_NONSINGLE_MARKERS = (
    "(non-sealed)",
    "(bi",
    "(mi",
    "(di",
    "(dd",
)

_SHORT_REGIONAL_CODE = re.compile(r"\([A-Za-z]{1,4}\)")


def normalize_expansion_name(name: str) -> str:
    text = (name or "").replace("&amp;", "&").strip().lower()
    return re.sub(r"\s+", " ", text)


def normalize_card_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", (name or "").strip().lower())
    text = text.replace("&amp;", "&")
    text = re.sub(r"[^\w\s\-']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def has_short_regional_bracket_code(product_name: str) -> bool:
    return bool(_SHORT_REGIONAL_CODE.search(product_name or ""))


def is_non_tcg_nonsingle_product(product_name: str) -> bool:
    normalized = normalize_expansion_name(product_name)
    if "rush duel" in normalized:
        return True
    if has_short_regional_bracket_code(product_name):
        return True
    if "ocg" in normalized or "japan" in normalized:
        return True
    if "deck build pack" in normalized or "korean" in normalized:
        return True
    if "booster sp" in normalized:
        return True
    if "gold series 2013" in normalized or "gold series 2014" in normalized:
        return True
    return any(marker in normalized for marker in NON_TCG_NONSINGLE_MARKERS)


def excluded_nonsingle_expansion_ids(nonsingles: list[dict]) -> set[int]:
    excluded: set[int] = set()
    for row in nonsingles:
        exp_id = row.get("idExpansion")
        if exp_id is None:
            continue
        if is_non_tcg_nonsingle_product(str(row.get("name") or "")):
            excluded.add(int(exp_id))
    return excluded


def is_championship_prize_set(set_name: str) -> bool:
    normalized = normalize_expansion_name(set_name)
    return "championship" in normalized and "prize card" in normalized


def is_collectible_tin_set(set_name: str) -> bool:
    return "collectible tin" in normalize_expansion_name(set_name)


def product_line_matches_yugipedia_set(product_name: str, tcg_set_name: str) -> bool:
    product = normalize_expansion_name(product_name)
    set_needle = normalize_expansion_name(tcg_set_name_for_matching(tcg_set_name))
    for qualifier in LINE_QUALIFIERS:
        if qualifier in product and qualifier not in set_needle:
            return False
    return True


def tcg_set_name_for_matching(tcg_set_name: str) -> str:
    name = (tcg_set_name or "").strip()
    if not name:
        return name

    advent_match = re.match(
        r"^yu-gi-oh!\s+advent calendar\s+\((\d{4})\)\s*$",
        name,
        flags=re.IGNORECASE,
    )
    if advent_match:
        return f"Advent Calendar {advent_match.group(1)}"

    transformed = re.sub(r"^yu-gi-oh!\s+", "", name, flags=re.IGNORECASE)
    transformed = re.sub(r"\s+prize cards?$", "", transformed, flags=re.IGNORECASE).strip()
    return transformed or name


def structure_deck_cardmarket_name(tcg_set_name: str) -> str | None:
    base = tcg_set_name_for_matching(tcg_set_name)
    normalized = normalize_expansion_name(base)
    if "structure deck" not in normalized:
        return None
    if re.match(r"^structure deck\s*:", normalized):
        return None
    match = re.match(r"^(.+?)\s+structure deck\s*$", base, flags=re.IGNORECASE)
    if not match:
        return None
    return f"Structure Deck: {match.group(1).strip()}"


def expansion_name_contains(
    product_name: str,
    tcg_set_name: str,
    *,
    matching_name: str | None = None,
) -> bool:
    product = normalize_expansion_name(product_name)
    if matching_name is not None:
        needle = normalize_expansion_name(matching_name)
    else:
        needle = normalize_expansion_name(tcg_set_name_for_matching(tcg_set_name))
    if not needle:
        return False
    return needle in product
