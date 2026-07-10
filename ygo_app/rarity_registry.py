"""Central rarity registry: canonical names/codes and cross-portal aliases."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ygo_app.utils import normalize_rarity_code, rarity_display

# Canonical seed aligned with rarity_price_ranks (alembic 014).
RARITY_ROWS: list[tuple[int, str, str]] = [
    (1, "Common", "C"),
    (2, "Normal Rare", "N"),
    (3, "Short Print", "SP"),
    (4, "Super Short Print", "SSP"),
    (5, "Normal Parallel Rare (Parallel Common)", "NPR"),
    (6, "Duel Terminal Normal Parallel Rare", "DNPR"),
    (7, "Rare", "R"),
    (8, "Duel Terminal Normal Rare Parallel Rare", "DNRPR"),
    (9, "Duel Terminal Rare Parallel Rare", "DRPR"),
    (10, "Super Rare", "SR"),
    (11, "Holofoil Rare", "HFR"),
    (12, "Super Parallel Rare", "SPR"),
    (13, "Duel Terminal Super Parallel Rare", "DSPR"),
    (14, "Starfoil Rare", "SFR"),
    (15, "Mosaic Rare", "MSR"),
    (16, "Shatterfoil Rare", "SHR"),
    (17, "Millennium Rare", "MR"),
    (18, "Ultra Rare", "UR"),
    (19, "Ultra Parallel Rare", "UPR"),
    (20, "Duel Terminal Ultra Parallel Rare", "DUPR"),
    (21, "Gold Rare", "GUR"),
    (22, "Ultimate Rare", "UtR"),
    (23, "Secret Rare", "ScR"),
    (24, "Ultra Secret Rare", "UScR"),
    (25, "Secret Ultra Rare", "ScUR"),
    (26, "Duel Terminal Secret Parallel Rare", "DScPR"),
    (27, "Gold Secret Rare", "GScR"),
    (28, "Ghost/Gold Rare", "GGR"),
    (29, "Premium Gold Rare", "PGR"),
    (30, "Platinum Rare", "PL"),
    (31, "Collector's Rare", "CR"),
    (32, "Ultra Rare (Pharaoh's Rare)", "UR(PR)"),
    (33, "Ghost Rare", "GR"),
    (34, "Starlight Rare", "SLR"),
    (35, "Prismatic Collector's Rare", "CR"),
    (36, "Prismatic Ultimate Rare", "UtR"),
    (37, "Platinum Secret Rare", "PlScR"),
    (38, "Extra Secret Rare", "EXSE"),
    (39, "10000 Secret Rare", "10000 SE"),
    (40, "Prismatic Secret Rare", "PScR"),
    (41, "Quarter Century Secret Rare", "QCSR"),
    (42, "Grand Master Rare", "GMR"),
]

# Portal-specific abbreviations beyond the canonical code and full name.
EXTRA_ALIASES: dict[str, list[str]] = {
    "Quarter Century Secret Rare": ["QCScR", "QCR"],
    "Starlight Rare": ["StR"],
    "Prismatic Secret Rare": ["PSR"],
    "10000 Secret Rare": ["10000ScR"],
}

_ALIASES_JSON = Path(__file__).resolve().parent / "data" / "rarity_aliases.json"


@dataclass(frozen=True)
class ResolvedRarity:
    name: str
    code: str
    normalized_code: str


@dataclass(frozen=True)
class _RarityEntry:
    name: str
    code: str
    normalized_code: str
    aliases: frozenset[str]


def _alias_key(value: str) -> str:
    return (value or "").strip().casefold()


def _bare_code(value: str) -> str:
    text = (value or "").strip()
    if text.startswith("(") and text.endswith(")"):
        return text[1:-1].strip()
    return text


def _load_json_aliases() -> list[tuple[str, str]]:
    if not _ALIASES_JSON.is_file():
        return []
    try:
        payload = json.loads(_ALIASES_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("aliases")
    if not isinstance(rows, list):
        return []
    out: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        alias = str(row.get("alias") or "").strip()
        canonical_name = str(row.get("canonical_name") or "").strip()
        if alias and canonical_name:
            out.append((alias, canonical_name))
    return out


def _build_registry() -> tuple[dict[str, _RarityEntry], dict[str, str]]:
    entries_by_name: dict[str, _RarityEntry] = {}
    alias_to_name: dict[str, str] = {}

    def _register_alias(alias: str, canonical_name: str, *, code_alias: bool = False) -> None:
        key = _alias_key(alias)
        if not key:
            return
        existing = alias_to_name.get(key)
        if existing is not None and existing != canonical_name:
            if code_alias:
                return
            raise ValueError(
                f"Conflicting rarity alias {alias!r}: "
                f"{existing!r} vs {canonical_name!r}"
            )
        alias_to_name[key] = canonical_name

    for _order, name, code in RARITY_ROWS:
        normalized_code = normalize_rarity_code(code)
        aliases: set[str] = {code, name, normalized_code, f"({name})"}
        for extra in EXTRA_ALIASES.get(name, []):
            aliases.add(extra)
            aliases.add(normalize_rarity_code(extra))
        entry = _RarityEntry(
            name=name,
            code=code,
            normalized_code=normalized_code,
            aliases=frozenset(aliases),
        )
        entries_by_name[name] = entry
        _register_alias(name, name)
        _register_alias(f"({name})", name)
        _register_alias(code, name, code_alias=True)
        _register_alias(normalized_code, name, code_alias=True)
        for extra in EXTRA_ALIASES.get(name, []):
            _register_alias(extra, name, code_alias=True)
            _register_alias(normalize_rarity_code(extra), name, code_alias=True)

    for alias, canonical_name in _load_json_aliases():
        if canonical_name not in entries_by_name:
            continue
        entry = entries_by_name[canonical_name]
        merged = set(entry.aliases)
        merged.add(alias)
        merged.add(normalize_rarity_code(alias))
        updated = _RarityEntry(
            name=entry.name,
            code=entry.code,
            normalized_code=entry.normalized_code,
            aliases=frozenset(merged),
        )
        entries_by_name[canonical_name] = updated
        for value in merged:
            is_code = value == entry.code or value == entry.normalized_code
            _register_alias(value, canonical_name, code_alias=is_code)

    return entries_by_name, alias_to_name


@lru_cache(maxsize=1)
def _registry() -> tuple[dict[str, _RarityEntry], dict[str, str]]:
    return _build_registry()


def clear_rarity_registry_cache() -> None:
    """Test helper: reload JSON aliases after patching the file."""
    _registry.cache_clear()


def resolve_rarity(raw: str | None) -> ResolvedRarity | None:
    """Map a bare code, parenthesized code, or full name to a canonical rarity."""
    text = (raw or "").strip()
    if not text:
        return None
    entries_by_name, alias_to_name = _registry()
    canonical_name = alias_to_name.get(_alias_key(text))
    if canonical_name is None:
        canonical_name = alias_to_name.get(_alias_key(_bare_code(text)))
    if canonical_name is None:
        return None
    entry = entries_by_name[canonical_name]
    return ResolvedRarity(
        name=entry.name,
        code=entry.code,
        normalized_code=entry.normalized_code,
    )


def rarity_match_variants(raw: str | None) -> list[str]:
    """Ordered normalized codes to try when matching a printing."""
    resolved = resolve_rarity(raw)
    if resolved is None:
        normalized = normalize_rarity_code(raw or "")
        return [normalized] if normalized else []
    return _variants_for_entry(entries_by_name=_registry()[0], name=resolved.name)


def variants_for_printing(
    set_rarity_code: str | None,
    set_rarity_name: str | None = None,
) -> list[str]:
    """All normalized codes under which a catalog printing should be indexed."""
    seen: set[str] = set()
    ordered: list[str] = []

    def _add(value: str | None) -> None:
        if not value:
            return
        resolved = resolve_rarity(value)
        if resolved is not None:
            for variant in _variants_for_entry(_registry()[0], resolved.name):
                if variant not in seen:
                    seen.add(variant)
                    ordered.append(variant)
            return
        normalized = normalize_rarity_code(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)

    _add(set_rarity_code)
    if set_rarity_name and set_rarity_name != set_rarity_code:
        _add(set_rarity_name)
    return ordered


def _variants_for_entry(entries_by_name: dict[str, _RarityEntry], name: str) -> list[str]:
    entry = entries_by_name[name]
    ordered: list[str] = []
    seen: set[str] = set()
    for candidate in (entry.normalized_code, *sorted(entry.aliases)):
        normalized = normalize_rarity_code(candidate)
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def rarity_label_for_error(raw: str | None, resolved: ResolvedRarity | None) -> str:
    """Human-readable rarity fragment for import rejection messages."""
    display = rarity_display(normalize_rarity_code(raw or ""))
    if resolved is None:
        return display
    if display.casefold() == resolved.code.casefold() or display == resolved.name:
        return f"{display} ({resolved.name})"
    return f"{display} ({resolved.name})"


def rarity_code_for_name(rarity_name: str) -> str:
    """Return bare canonical code for Yugipedia/catalog ingest, or empty if unknown."""
    resolved = resolve_rarity(rarity_name)
    return resolved.code if resolved else ""
