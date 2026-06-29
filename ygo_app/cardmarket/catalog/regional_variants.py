"""Group Yugipedia regional set_code variants for Cardmarket catalog matching."""

from __future__ import annotations

import re
from collections import defaultdict

from ygo_app.cardmarket.catalog.rarity_guess import YugipediaPrintingRef

_REGIONAL_PREFIXES = ("EN", "E", "A", "FR", "DE", "IT", "SP", "PT")


def parse_yugipedia_set_code(set_code: str) -> tuple[str, str] | None:
    """Return (base_expansion, collector_suffix) from Yugipedia set_code."""
    code = (set_code or "").strip().upper()
    if "-" not in code:
        return None
    base, rest = code.split("-", 1)
    if not base or not rest:
        return None
    for prefix in _REGIONAL_PREFIXES:
        if rest.startswith(prefix) and len(rest) > len(prefix):
            rest = rest[len(prefix) :]
            break
    return base, rest


def normalize_collector_number(suffix: str) -> str:
    """Normalize collector suffix for grouping (strip leading zeros on digits)."""
    s = (suffix or "").strip().upper()
    if not s:
        return s
    if s.isdigit():
        return s.lstrip("0") or "0"
    match = re.match(r"^([A-Z]*?)0*(\d+)$", s)
    if match and match.group(1):
        return f"{match.group(1)}{match.group(2)}"
    return s


def collector_slot_key(set_code: str, rarity_code: str) -> tuple[str, str] | None:
    """Return (rarity_code, normalized_collector) for regional grouping."""
    parsed = parse_yugipedia_set_code(set_code)
    if not parsed:
        return None
    _, collector = parsed
    return (rarity_code.upper(), normalize_collector_number(collector))


def _representative_sort_key(ref: YugipediaPrintingRef) -> tuple[int, str]:
    """Prefer -EN regional form over legacy numeric-only codes."""
    code = ref.set_code.upper()
    if re.search(r"-EN[A-Z0-9]", code):
        return (0, code)
    return (1, code)


def group_regional_variant_refs(
    refs: list[YugipediaPrintingRef],
) -> list[tuple[YugipediaPrintingRef, list[YugipediaPrintingRef]]]:
    """
    Group refs by rarity + collector number (regional duplicates share a slot).

    Returns (representative, all_variants) per slot. Unparseable set_codes stay solo.
    """
    groups: dict[tuple[str, str], list[YugipediaPrintingRef]] = defaultdict(list)
    solo: list[YugipediaPrintingRef] = []

    for ref in refs:
        key = collector_slot_key(ref.set_code, ref.rarity_code)
        if key is None:
            solo.append(ref)
            continue
        groups[key].append(ref)

    result: list[tuple[YugipediaPrintingRef, list[YugipediaPrintingRef]]] = []
    for key in sorted(groups.keys()):
        members = groups[key]
        representative = min(members, key=_representative_sort_key)
        result.append((representative, members))

    for ref in solo:
        result.append((ref, [ref]))

    return result
