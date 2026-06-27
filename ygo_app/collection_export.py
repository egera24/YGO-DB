"""Export user collection to portal-specific CSV formats."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ygo_app.cardmarket.market_prices import (
    load_market_prices,
    market_prices_tuple,
    resolve_sell_price,
)
from ygo_app.models import (
    CollectionFolder,
    CollectionItem,
    CollectionItemFolder,
    Printing,
    PrintingMarketPrice,
)
from ygo_app.services import NO_FOLDER
from ygo_app.utils import rarity_display

DRAGONSHIELD_HEADERS = [
    "Folder Name",
    "Quantity",
    "Trade Quantity",
    "Card Name",
    "Set Code",
    "Set Name",
    "Card Number",
    "Rarity",
    "Condition",
    "Printing",
    "Language",
    "Price Bought",
    "Date Bought",
    "AVG",
    "LOW",
    "TREND",
    "Sell Price",
]


@dataclass(frozen=True)
class ExportRow:
    folder_name: str | None
    quantity: int
    trade_quantity: int
    card_name: str | None
    expansion_code: str | None
    set_name: str | None
    set_code: str
    rarity_code: str
    condition: str | None
    edition: str | None
    language: str | None
    price_bought: float | None
    date_bought: str | None
    avg_price: float
    low_price: float
    trend_price: float
    sell_price: float


@dataclass(frozen=True)
class ExportFormat:
    id: str
    label: str
    filename: str
    description: str
    write: Callable[[list[ExportRow]], str]


def _format_price(value: float | None) -> str:
    if value is None:
        return ""
    return str(value)


def _format_export_market_price(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return str(value)


def _item_base_row(
    item: CollectionItem,
    *,
    market_row: PrintingMarketPrice | None,
) -> dict:
    card_name = item.card_name
    set_name = item.set_name
    printing = item.linked_printing
    if printing is not None:
        if not set_name and printing.set_name:
            set_name = printing.set_name
        if not card_name and printing.card:
            card_name = printing.card.name
    low_price, avg_price, trend_price = market_prices_tuple(market_row)
    market_trend = market_row.trend_price if market_row is not None else None
    return {
        "trade_quantity": item.trade_quantity,
        "card_name": card_name,
        "expansion_code": item.expansion_code,
        "set_name": set_name,
        "set_code": item.set_code,
        "rarity_code": item.rarity_code,
        "condition": item.condition,
        "edition": item.edition or "Unlimited",
        "language": item.language,
        "price_bought": item.price_bought,
        "date_bought": item.date_bought,
        "avg_price": avg_price,
        "low_price": low_price,
        "trend_price": trend_price,
        "sell_price": resolve_sell_price(item.sell_price, market_trend),
    }


def _allocation_in_filters(
    folder_id: int | None, folder_filters: set[str] | None
) -> bool:
    if folder_filters is None:
        return True
    if folder_id is None:
        return NO_FOLDER in folder_filters
    return str(folder_id) in folder_filters


def validate_export_folder_ids(
    session: Session, user_id: int, folder_ids: list[str]
) -> set[str]:
    if not folder_ids:
        raise ValueError("Select at least one folder")
    validated: set[str] = set()
    for raw in folder_ids:
        token = raw.strip()
        if not token:
            raise ValueError("Select at least one folder")
        if token == NO_FOLDER:
            validated.add(NO_FOLDER)
            continue
        try:
            folder_id = int(token)
        except ValueError as exc:
            raise ValueError(f"Unknown folder: {token}") from exc
        folder = session.get(CollectionFolder, folder_id)
        if not folder or folder.user_id != user_id:
            raise ValueError("Folder not found")
        validated.add(str(folder_id))
    return validated


def _item_to_rows(
    item: CollectionItem,
    *,
    market_row: PrintingMarketPrice | None,
    folder_filters: set[str] | None = None,
) -> list[ExportRow]:
    base = _item_base_row(item, market_row=market_row)
    allocations = item.folder_allocations
    if not allocations:
        if not _allocation_in_filters(None, folder_filters):
            return []
        return [
            ExportRow(
                folder_name=None,
                quantity=item.quantity,
                **base,
            )
        ]
    rows: list[ExportRow] = []
    for allocation in allocations:
        if not _allocation_in_filters(allocation.folder_id, folder_filters):
            continue
        rows.append(
            ExportRow(
                folder_name=allocation.folder.name if allocation.folder else None,
                quantity=int(allocation.quantity),
                **base,
            )
        )
    return rows


def _write_dragonshield(rows: list[ExportRow]) -> str:
    buf = io.StringIO()
    buf.write('"sep=,"\n')
    writer = csv.DictWriter(buf, fieldnames=DRAGONSHIELD_HEADERS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "Folder Name": row.folder_name or "",
                "Quantity": row.quantity,
                "Trade Quantity": row.trade_quantity,
                "Card Name": row.card_name or "",
                "Set Code": row.expansion_code or "",
                "Set Name": row.set_name or "",
                "Card Number": row.set_code,
                "Rarity": rarity_display(row.rarity_code),
                "Condition": row.condition or "",
                "Printing": row.edition or "Unlimited",
                "Language": row.language or "",
                "Price Bought": _format_price(row.price_bought),
                "Date Bought": row.date_bought or "",
                "AVG": _format_export_market_price(row.avg_price),
                "LOW": _format_export_market_price(row.low_price),
                "TREND": _format_export_market_price(row.trend_price),
                "Sell Price": _format_export_market_price(row.sell_price),
            }
        )
    return buf.getvalue()


def load_collection_for_export(
    session: Session,
    user_id: int,
    *,
    folder_filters: set[str] | None = None,
) -> list[ExportRow]:
    stmt = (
        select(CollectionItem)
        .where(CollectionItem.user_id == user_id)
        .options(
            joinedload(CollectionItem.linked_printing).joinedload(Printing.card),
            joinedload(CollectionItem.folder_allocations).joinedload(
                CollectionItemFolder.folder
            ),
        )
        .order_by(CollectionItem.set_code)
    )
    items = session.execute(stmt).unique().scalars().all()
    keys = [(item.set_code, item.rarity_code) for item in items]
    market_map = load_market_prices(session, keys)
    rows: list[ExportRow] = []
    for item in items:
        market_row = market_map.get((item.set_code, item.rarity_code))
        rows.extend(
            _item_to_rows(item, market_row=market_row, folder_filters=folder_filters)
        )
    return rows


FORMATS: dict[str, ExportFormat] = {
    "dragonshield": ExportFormat(
        id="dragonshield",
        label="DragonShield",
        filename="ygo_collection_dragonshield.csv",
        description=(
            "DragonShield folder CSV. Can be re-imported with Import my collection."
        ),
        write=_write_dragonshield,
    ),
}


def list_export_formats() -> list[dict]:
    return [
        {
            "id": fmt.id,
            "label": fmt.label,
            "filename": fmt.filename,
            "description": fmt.description,
        }
        for fmt in FORMATS.values()
    ]


def export_collection_csv(
    session: Session,
    *,
    user_id: int,
    format_id: str,
    folder_ids: list[str] | None = None,
) -> tuple[str, str, str]:
    fmt = FORMATS.get(format_id)
    if fmt is None:
        raise ValueError(f"Unknown export format: {format_id}")
    folder_filters = None
    if folder_ids is not None:
        folder_filters = validate_export_folder_ids(session, user_id, folder_ids)
    rows = load_collection_for_export(
        session, user_id, folder_filters=folder_filters
    )
    csv_text = fmt.write(rows)
    return csv_text, "text/csv; charset=utf-8", fmt.filename
