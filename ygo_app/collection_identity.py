"""Collection row identity: set code + rarity + edition + condition."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ygo_app.models import CollectionItem

CollectionItemKey = tuple[str, str, str, str | None]

COLLECTION_CONDITIONS = (
    "Mint",
    "NearMint",
    "Excellent",
    "Good",
    "LightPlayed",
    "Played",
    "Poor",
)

COLLECTION_EDITIONS = ("Unlimited", "1st Edition", "Limited Edition")


def _alias_key(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _build_alias_map(pairs: list[tuple[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for alias, canonical in pairs:
        key = _alias_key(alias)
        if key in out and out[key] != canonical:
            raise ValueError(f"Conflicting alias {alias!r}")
        out[key] = canonical
    return out


_CONDITION_ALIAS_PAIRS: list[tuple[str, str]] = [
    ("mint", "Mint"),
    ("mt", "Mint"),
    ("nearmint", "NearMint"),
    ("near mint", "NearMint"),
    ("near-mint", "NearMint"),
    ("nm", "NearMint"),
    ("excellent", "Excellent"),
    ("ex", "Excellent"),
    ("good", "Good"),
    ("gd", "Good"),
    ("lightplayed", "LightPlayed"),
    ("light played", "LightPlayed"),
    ("light-played", "LightPlayed"),
    ("lp", "LightPlayed"),
    ("played", "Played"),
    ("pl", "Played"),
    ("poor", "Poor"),
    ("po", "Poor"),
]
_CONDITION_ALIASES = _build_alias_map(_CONDITION_ALIAS_PAIRS)

_EDITION_ALIAS_PAIRS: list[tuple[str, str]] = [
    ("unlimited", "Unlimited"),
    ("ue", "Unlimited"),
    ("1st edition", "1st Edition"),
    ("1st ed", "1st Edition"),
    ("1st ed.", "1st Edition"),
    ("first edition", "1st Edition"),
    ("first ed", "1st Edition"),
    ("first ed.", "1st Edition"),
    ("1st", "1st Edition"),
    ("1stedition", "1st Edition"),
    ("limited edition", "Limited Edition"),
    ("limited ed", "Limited Edition"),
    ("limited ed.", "Limited Edition"),
    ("limited", "Limited Edition"),
    ("le", "Limited Edition"),
]
_EDITION_ALIASES = _build_alias_map(_EDITION_ALIAS_PAIRS)


def normalize_collection_edition(edition: str | None) -> str:
    """Empty/None → Unlimited; map DragonShield/UI aliases to canonical edition."""
    if edition is None:
        return "Unlimited"
    stripped = edition.strip()
    if not stripped:
        return "Unlimited"
    if stripped in COLLECTION_EDITIONS:
        return stripped
    alias = _EDITION_ALIASES.get(_alias_key(stripped))
    if alias is not None:
        return alias
    return stripped


def normalize_collection_condition(condition: str | None) -> str | None:
    """Empty → None; map DragonShield/UI aliases to canonical condition."""
    if condition is None:
        return None
    stripped = condition.strip()
    if not stripped:
        return None
    if stripped in COLLECTION_CONDITIONS:
        return stripped
    alias = _CONDITION_ALIASES.get(_alias_key(stripped))
    if alias is not None:
        return alias
    return stripped


def collection_item_key(
    set_code: str,
    rarity_code: str,
    *,
    edition: str | None,
    condition: str | None,
) -> CollectionItemKey:
    return (
        set_code,
        rarity_code,
        normalize_collection_edition(edition),
        normalize_collection_condition(condition),
    )


def collection_item_key_from_row(item) -> CollectionItemKey:
    """Build identity key from a CollectionItem ORM row."""
    return collection_item_key(
        item.set_code,
        item.rarity_code,
        edition=item.edition,
        condition=item.condition,
    )


def find_collection_item_by_identity(
    session: Session,
    *,
    user_id: int,
    set_code: str,
    rarity_code: str,
    edition: str | None,
    condition: str | None,
    exclude_item_id: int | None = None,
) -> CollectionItem | None:
    from sqlalchemy import select

    from ygo_app.models import CollectionItem

    target_key = collection_item_key(
        set_code,
        rarity_code,
        edition=edition,
        condition=condition,
    )
    candidates = (
        session.execute(
            select(CollectionItem)
            .where(
                CollectionItem.user_id == user_id,
                CollectionItem.set_code == set_code,
                CollectionItem.rarity_code == rarity_code,
            )
        )
        .scalars()
        .all()
    )
    for candidate in candidates:
        if exclude_item_id is not None and candidate.id == exclude_item_id:
            continue
        if collection_item_key_from_row(candidate) == target_key:
            return candidate
    return None
