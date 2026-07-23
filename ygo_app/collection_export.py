"""Export user collection to portal-specific CSV and Excel formats."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ygo_app.cardmarket.market_prices import (
    load_market_prices,
    market_prices_tuple,
    resolve_sell_price,
)
from ygo_app.collection_identity import (
    normalize_collection_condition,
    normalize_collection_edition,
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
    "Notes",
]

XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
CSV_MEDIA_TYPE = "text/csv; charset=utf-8"


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
    notes: str | None


@dataclass(frozen=True)
class ExportFormat:
    id: str
    label: str
    filename: str
    description: str
    media_type: str
    write: Callable[[list[ExportRow]], bytes]


def _format_price(value: float | None) -> str:
    if value is None:
        return ""
    return str(value)


def _format_export_market_price(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return str(value)


def _row_cells(row: ExportRow) -> list:
    return [
        row.folder_name or "",
        row.quantity,
        row.trade_quantity,
        row.card_name or "",
        row.expansion_code or "",
        row.set_name or "",
        row.set_code,
        rarity_display(row.rarity_code),
        row.condition or "",
        row.edition or "Unlimited",
        row.language or "",
        _format_price(row.price_bought),
        row.date_bought or "",
        _format_export_market_price(row.avg_price),
        _format_export_market_price(row.low_price),
        _format_export_market_price(row.trend_price),
        _format_export_market_price(row.sell_price),
        row.notes or "",
    ]


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
        "condition": normalize_collection_condition(item.condition),
        "edition": normalize_collection_edition(item.edition),
        "language": item.language,
        "price_bought": item.price_bought,
        "date_bought": item.date_bought,
        "avg_price": avg_price,
        "low_price": low_price,
        "trend_price": trend_price,
        "sell_price": resolve_sell_price(item.sell_price, market_trend),
        "notes": item.notes,
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


def _write_dragonshield(rows: list[ExportRow]) -> bytes:
    buf = io.StringIO()
    buf.write('"sep=,"\n')
    writer = csv.DictWriter(buf, fieldnames=DRAGONSHIELD_HEADERS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        cells = _row_cells(row)
        writer.writerow(dict(zip(DRAGONSHIELD_HEADERS, cells, strict=True)))
    return buf.getvalue().encode("utf-8")


def _write_excel(rows: list[ExportRow]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Collection"
    ws.append(list(DRAGONSHIELD_HEADERS))
    for row in rows:
        ws.append(_row_cells(row))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


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
        media_type=CSV_MEDIA_TYPE,
        write=_write_dragonshield,
    ),
    "excel": ExportFormat(
        id="excel",
        label="Excel",
        filename="ygo_collection.xlsx",
        description="Excel workbook (.xlsx) with the same columns as DragonShield.",
        media_type=XLSX_MEDIA_TYPE,
        write=_write_excel,
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


def export_collection(
    session: Session,
    *,
    user_id: int,
    format_id: str,
    folder_ids: list[str] | None = None,
) -> tuple[bytes, str, str]:
    fmt = FORMATS.get(format_id)
    if fmt is None:
        raise ValueError(f"Unknown export format: {format_id}")
    folder_filters = None
    if folder_ids is not None:
        folder_filters = validate_export_folder_ids(session, user_id, folder_ids)
    rows = load_collection_for_export(
        session, user_id, folder_filters=folder_filters
    )
    return fmt.write(rows), fmt.media_type, fmt.filename


def export_collection_csv(
    session: Session,
    *,
    user_id: int,
    format_id: str,
    folder_ids: list[str] | None = None,
) -> tuple[str, str, str]:
    """CSV-oriented helper: returns decoded text for CSV formats."""
    content, media_type, filename = export_collection(
        session,
        user_id=user_id,
        format_id=format_id,
        folder_ids=folder_ids,
    )
    if not media_type.startswith("text/csv"):
        raise ValueError(f"Format {format_id!r} is not a CSV export")
    return content.decode("utf-8"), media_type, filename
