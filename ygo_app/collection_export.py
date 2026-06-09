"""Export user collection to portal-specific CSV formats."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ygo_app.models import CollectionItem, Printing
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
    avg_price: float | None
    low_price: float | None
    trend_price: float | None


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


def _item_to_row(item: CollectionItem) -> ExportRow:
    card_name = item.card_name
    set_name = item.set_name
    printing = item.linked_printing
    if printing is not None:
        if not set_name and printing.set_name:
            set_name = printing.set_name
        if not card_name and printing.card:
            card_name = printing.card.name
    return ExportRow(
        folder_name=item.folder_name,
        quantity=item.quantity,
        trade_quantity=item.trade_quantity,
        card_name=card_name,
        expansion_code=item.expansion_code,
        set_name=set_name,
        set_code=item.set_code,
        rarity_code=item.rarity_code,
        condition=item.condition,
        edition=item.edition or "Unlimited",
        language=item.language,
        price_bought=item.price_bought,
        date_bought=item.date_bought,
        avg_price=item.avg_price,
        low_price=item.low_price,
        trend_price=item.trend_price,
    )


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
                "AVG": _format_price(row.avg_price),
                "LOW": _format_price(row.low_price),
                "TREND": _format_price(row.trend_price),
            }
        )
    return buf.getvalue()


def load_collection_for_export(session: Session, user_id: int) -> list[ExportRow]:
    stmt = (
        select(CollectionItem)
        .where(CollectionItem.user_id == user_id)
        .options(joinedload(CollectionItem.linked_printing).joinedload(Printing.card))
        .order_by(CollectionItem.set_code)
    )
    items = session.execute(stmt).unique().scalars().all()
    return [_item_to_row(item) for item in items]


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
    session: Session, *, user_id: int, format_id: str
) -> tuple[str, str, str]:
    fmt = FORMATS.get(format_id)
    if fmt is None:
        raise ValueError(f"Unknown export format: {format_id}")
    rows = load_collection_for_export(session, user_id)
    csv_text = fmt.write(rows)
    return csv_text, "text/csv; charset=utf-8", fmt.filename
