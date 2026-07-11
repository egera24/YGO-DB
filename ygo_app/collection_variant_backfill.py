"""Backfill canonical condition/edition values and merge alias-duplicate rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from ygo_app.collection_identity import (
    collection_item_key,
    normalize_collection_condition,
    normalize_collection_edition,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ygo_app.models import CollectionItem


def _merge_folder_allocations(survivor: CollectionItem, other: CollectionItem) -> None:
    from ygo_app.models import CollectionItemFolder

    for alloc in list(other.folder_allocations):
        match = next(
            (row for row in survivor.folder_allocations if row.folder_id == alloc.folder_id),
            None,
        )
        if match is not None:
            match.quantity += alloc.quantity
        else:
            survivor.folder_allocations.append(
                CollectionItemFolder(folder_id=alloc.folder_id, quantity=alloc.quantity)
            )


def _apply_normalized_fields(item: CollectionItem) -> bool:
    new_condition = normalize_collection_condition(item.condition)
    new_edition = normalize_collection_edition(item.edition)
    changed = item.condition != new_condition or item.edition != new_edition
    item.condition = new_condition
    item.edition = new_edition
    return changed


def normalize_collection_variants_in_db(
    session: Session,
    *,
    user_id: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    from ygo_app.models import CollectionItem

    stmt = (
        select(CollectionItem)
        .options(joinedload(CollectionItem.folder_allocations))
        .order_by(CollectionItem.user_id, CollectionItem.id)
    )
    if user_id is not None:
        stmt = stmt.where(CollectionItem.user_id == user_id)
    items = list(session.execute(stmt).unique().scalars().all())

    groups: dict[tuple[int, str, str, str, str | None], list[CollectionItem]] = {}
    for item in items:
        key = (
            item.user_id,
            *collection_item_key(
                item.set_code,
                item.rarity_code,
                edition=item.edition,
                condition=item.condition,
            ),
        )
        groups.setdefault(key, []).append(item)

    updated = 0
    merged = 0
    deleted = 0

    for group in groups.values():
        group.sort(key=lambda row: row.id)
        survivor = group[0]

        if len(group) > 1:
            for other in group[1:]:
                if not dry_run:
                    survivor.quantity += other.quantity
                    survivor.trade_quantity += other.trade_quantity
                    if other.notes and not survivor.notes:
                        survivor.notes = other.notes
                    if other.sell_price is not None and survivor.sell_price is None:
                        survivor.sell_price = other.sell_price
                    _merge_folder_allocations(survivor, other)
                    session.delete(other)
                deleted += 1
            merged += len(group) - 1

        if _apply_normalized_fields(survivor) if not dry_run else (
            normalize_collection_condition(survivor.condition) != survivor.condition
            or normalize_collection_edition(survivor.edition) != survivor.edition
        ):
            updated += 1

    if not dry_run:
        session.commit()

    return {
        "rows_updated": updated,
        "rows_merged": merged,
        "rows_deleted": deleted,
        "groups_processed": len(groups),
    }


def dry_run_collection_variants(
    session: Session,
    *,
    user_id: int | None = None,
) -> dict[str, int]:
    return normalize_collection_variants_in_db(
        session,
        user_id=user_id,
        dry_run=True,
    )
