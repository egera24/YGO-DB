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
    text = unicodedata.normalize("NFKC", (name or "").replace("&amp;", "&").strip().lower())
    text = text.replace("\u2019", "'").replace("\u2018", "'")
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
    if "25th anniversary edition" in normalized:
        return True
    if "sacred beasts of chaos" in normalized:
        return True
    if "promotional" in normalized or "participation" in normalized:
        return True
    return any(marker in normalized for marker in NON_TCG_NONSINGLE_MARKERS)


def is_expansion_level_nonsingle_contaminant(product_name: str) -> bool:
    """True when any product in an expansion should exclude the whole idExpansion."""
    if not is_non_tcg_nonsingle_product(product_name):
        return False
    return "(non-sealed)" not in normalize_expansion_name(product_name)


def excluded_nonsingle_expansion_ids(nonsingles: list[dict]) -> set[int]:
    excluded: set[int] = set()
    for row in nonsingles:
        exp_id = row.get("idExpansion")
        if exp_id is None:
            continue
        if is_expansion_level_nonsingle_contaminant(str(row.get("name") or "")):
            excluded.add(int(exp_id))
    return excluded


def is_championship_prize_set(set_name: str) -> bool:
    normalized = normalize_expansion_name(set_name)
    return "championship" in normalized and "prize card" in normalized


def is_collectible_tin_set(set_name: str) -> bool:
    return "collectible tin" in normalize_expansion_name(set_name)


def is_promotional_or_participation_set(set_name: str) -> bool:
    normalized = normalize_expansion_name(set_name)
    return "promotional" in normalized or "participation" in normalized


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


def dark_revelation_cardmarket_name(tcg_set_name: str) -> str | None:
    base = tcg_set_name_for_matching(tcg_set_name)
    match = re.match(r"^dark revelation volume (\d+)\s*$", base, flags=re.IGNORECASE)
    if not match:
        return None
    return f"Dark Revelation {match.group(1)}"


def legendary_duelists_subtitle_name(tcg_set_name: str) -> str | None:
    base = tcg_set_name_for_matching(tcg_set_name)
    match = re.match(r"^legendary duelists:\s+(.+)$", base, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


def starter_deck_cardmarket_name(tcg_set_name: str) -> str | None:
    base = tcg_set_name_for_matching(tcg_set_name)
    match = re.match(r"^starter deck:\s+yu-gi-oh!\s+(.+)$", base, flags=re.IGNORECASE)
    if match:
        return f"{match.group(1).strip()} Starter Deck"
    match = re.match(r"^starter deck:\s+(.+)$", base, flags=re.IGNORECASE)
    if match:
        return f"{match.group(1).strip()} Starter Deck"
    return None


def alternate_matching_names(tcg_set_name: str) -> list[str]:
    names: list[str] = []
    for helper in (
        structure_deck_cardmarket_name,
        dark_revelation_cardmarket_name,
        legendary_duelists_subtitle_name,
        starter_deck_cardmarket_name,
    ):
        alternate = helper(tcg_set_name)
        if alternate:
            names.append(alternate)
    return names


def _trailing_digit_boundary_ok(product: str, needle: str, pos: int) -> bool:
    if not needle or not needle[-1].isdigit():
        return True
    end = pos + len(needle)
    if end >= len(product):
        return True
    return not product[end].isdigit()


def _colon_subtitle_after_match(product: str, needle: str, pos: int) -> bool:
    end = pos + len(needle)
    rest = product[end:].lstrip()
    if not rest.startswith(":"):
        return False
    subtitle = rest[1:].lstrip()
    if subtitle.startswith(('"', "“", "”")):
        return False
    if "mega-pack" in subtitle or subtitle.endswith(" tin"):
        return False
    return True


def _needle_match_in_product(product: str, needle: str, *, allow_colon_subtitle: bool) -> bool:
    if not needle:
        return False
    idx = 0
    while True:
        pos = product.find(needle, idx)
        if pos == -1:
            return False
        if not _trailing_digit_boundary_ok(product, needle, pos):
            idx = pos + 1
            continue
        if not allow_colon_subtitle and _colon_subtitle_after_match(product, needle, pos):
            idx = pos + 1
            continue
        return True


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
    allow_colon_subtitle = ":" in needle
    return _needle_match_in_product(
        product, needle, allow_colon_subtitle=allow_colon_subtitle
    )
