"""Manual Yugipedia abbr → Cardmarket nonsingle name aliases."""

from __future__ import annotations

from ygo_app.cardmarket.catalog.normalize import normalize_expansion_name

EXPANSION_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    # Gold Series
    "GLD1": ("Gold Series 1 Booster",),
    "GLD2": ("Gold Series 2 Booster",),
    "GLD3": ("Gold Series 3 Booster",),
    "GLD4": ("Gold Series 4: Pyramids Edition Booster",),
    "GLD5": ("Gold Series 5: Haunted Mine Booster",),
    # Hidden Arsenal
    "HA01": ("Hidden Arsenal",),
    "HA02": ("Hidden Arsenal 2 Booster",),
    "HA04": ("Hidden Arsenal 4 Booster",),
    "HA05": ("Hidden Arsenal 5 Booster",),
    "HA06": ("Hidden Arsenal 6 Booster",),
    "HA07": ("Hidden Arsenal 7 Booster",),
    "HAC1": ("Hidden Arsenal: Chapter 1 Booster",),
    "HASE": ("Hidden Arsenal: Special Edition",),
    "H5SE": ("Hidden Arsenal 5: Special Edition",),
    # Legendary Collection
    "LC01": ("Legendary Collection",),
    "LC02": ("Legendary Collection 2",),
    "LC03": ("Legendary Collection 3",),
    "LC04": ("Legendary Collection 4",),
    "LC05": (
        "Legendary Collection 5D's: Mega Pack Booster",
        "Legendary Collection 5D's: Promo Box",
    ),
    "LC06": (
        "Legendary Collection Kaiba",
        "Legendary Collection Kaiba Mega Pack Booster",
        "Legendary Collection Kaiba (2025 Reprint)",
    ),
    "LC5D": ("Legendary Collection 5D's: Mega Pack Booster",),
    "LCGX": ("Legendary Collection 2: Mega Pack Booster",),
    "LCJW": ("Legendary Collection 4: Mega Pack Booster",),
    "LCYW": ("Legendary Collection 3: Mega Pack Booster",),
    "LCKC": ("Legendary Collection Kaiba Mega Pack Booster",),
}


def expansion_aliases_for_abbr(abbr: str) -> tuple[str, ...] | None:
    return EXPANSION_NAME_ALIASES.get(abbr.upper())


def _alias_suffix_allowed(suffix: str) -> bool:
    suffix = suffix.strip()
    if not suffix:
        return True
    if suffix.startswith("booster"):
        return True
    if suffix == "box":
        return True
    return False


def nonsingle_matches_alias(product_name: str, alias: str) -> bool:
    product_norm = normalize_expansion_name(product_name)
    alias_norm = normalize_expansion_name(alias)
    if not alias_norm or not product_norm.startswith(alias_norm):
        return False
    remainder = product_norm[len(alias_norm) :]
    if not remainder:
        return True
    stripped = remainder.lstrip()
    if stripped and stripped[0].isdigit():
        return False
    return _alias_suffix_allowed(stripped)
