"""SQL helpers for card search and collection list ordering."""

from __future__ import annotations

from sqlalchemy import case, func, literal, select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from ygo_app.models import (
    Card,
    CollectionFolder,
    CollectionItem,
    CollectionItemFolder,
    Printing,
    TcgSet,
)


CARD_SEARCH_SORT_FIELDS = frozenset({"name", "passcode", "release_date", "owned_quantity"})
COLLECTION_SORT_FIELDS = frozenset(
    {
        "set_code",
        "card_name",
        "folder_name",
        "quantity",
        "trade_quantity",
        "passcode",
        "release_date",
    }
)


def printing_expansion_abbr_sql(
    column: ColumnElement | InstrumentedAttribute,
    dialect: str,
) -> ColumnElement:
    if dialect == "postgresql":
        return func.upper(func.split_part(column, "-", 1))
    dash_pos = func.instr(column, "-")
    return case(
        (dash_pos > 0, func.upper(func.substr(column, 1, dash_pos - 1))),
        else_=None,
    )


def apply_sort_direction(
    column: ColumnElement,
    sort_dir: str,
    *,
    nulls: bool = False,
    nulls_last: bool = False,
):
    descending = sort_dir == "desc"
    if nulls_last:
        if descending:
            return column.desc().nulls_last()
        return column.asc().nulls_last()
    if nulls:
        if descending:
            return column.desc().nulls_first()
        return column.asc().nulls_last()
    if descending:
        return column.desc()
    return column.asc()


def card_owned_quantity_subquery(user_id: int | None):
    if user_id is None:
        return literal(0)
    return (
        select(func.coalesce(func.sum(CollectionItem.quantity), 0))
        .select_from(Printing)
        .join(
            CollectionItem,
            (CollectionItem.set_code == Printing.set_code)
            & (CollectionItem.rarity_code == Printing.set_rarity_code)
            & (CollectionItem.user_id == user_id),
        )
        .where(Printing.card_id == Card.id)
        .correlate(Card)
        .scalar_subquery()
    )


def build_card_search_order_by(
    sort: str,
    sort_dir: str,
    user_id: int | None,
    *,
    dialect: str,
) -> list:
    field = sort if sort in CARD_SEARCH_SORT_FIELDS else "name"
    direction = sort_dir if sort_dir in ("asc", "desc") else "asc"
    tie = apply_sort_direction(Card.id, direction)

    if field == "passcode":
        return [apply_sort_direction(Card.passcode, direction, nulls=True), tie]
    if field == "release_date":
        return [
            apply_sort_direction(
                Card.latest_release_date, direction, nulls_last=True
            ),
            tie,
        ]
    if field == "owned_quantity":
        owned = card_owned_quantity_subquery(user_id)
        return [apply_sort_direction(owned, direction), tie]
    return [apply_sort_direction(Card.name, direction), tie]


def collection_folder_name_subquery():
    return (
        select(CollectionFolder.name)
        .join(
            CollectionItemFolder,
            CollectionItemFolder.folder_id == CollectionFolder.id,
        )
        .where(CollectionItemFolder.collection_item_id == CollectionItem.id)
        .order_by(CollectionFolder.name)
        .limit(1)
        .scalar_subquery()
    )


def apply_collection_sort_joins(stmt, sort: str, *, dialect: str):
    if sort == "passcode":
        return stmt.outerjoin(
            Printing,
            (Printing.set_code == CollectionItem.set_code)
            & (Printing.set_rarity_code == CollectionItem.rarity_code),
        ).outerjoin(Card, Card.id == Printing.card_id)
    if sort == "release_date":
        abbr_expr = printing_expansion_abbr_sql(CollectionItem.set_code, dialect)
        return stmt.outerjoin(
            TcgSet,
            (TcgSet.abbr == abbr_expr) & TcgSet.release_date.is_not(None),
        )
    return stmt


def build_collection_order_by(sort: str, sort_dir: str) -> list:
    field = sort if sort in COLLECTION_SORT_FIELDS else "set_code"
    direction = sort_dir if sort_dir in ("asc", "desc") else "asc"
    tie = apply_sort_direction(CollectionItem.id, direction)

    if field == "folder_name":
        order_col = collection_folder_name_subquery()
        return [apply_sort_direction(order_col, direction, nulls=True), tie]

    columns = {
        "set_code": CollectionItem.set_code,
        "card_name": CollectionItem.card_name,
        "quantity": CollectionItem.quantity,
        "trade_quantity": CollectionItem.trade_quantity,
        "passcode": Card.passcode,
        "release_date": TcgSet.release_date,
    }
    order_col = columns.get(field, CollectionItem.set_code)
    if field == "release_date":
        return [apply_sort_direction(order_col, direction, nulls_last=True), tie]
    nulls = field == "passcode"
    return [apply_sort_direction(order_col, direction, nulls=nulls), tie]
