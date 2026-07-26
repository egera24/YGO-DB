"""Export public trade lists to Excel."""

from __future__ import annotations

import io
import re

from openpyxl import Workbook
from sqlalchemy.orm import Session

from ygo_app.collection_export import XLSX_MEDIA_TYPE
from ygo_app.services import list_public_trade_items

TRADE_HEADERS = [
    "Card Name",
    "Set Code",
    "Set Name",
    "Rarity",
    "Edition",
    "Condition",
    "Trade Quantity",
    "Sell Price",
]

TRADE_ORDER_HEADERS = [
    "Card Name",
    "Set Code",
    "Set Name",
    "Rarity",
    "Condition",
    "Quantity",
    "List Price",
    "Offer Price",
    "Comment",
]

_PAGE_SIZE = 500
_SLUG_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def trade_export_filename(slug: str) -> str:
    safe = _SLUG_SAFE.sub("-", (slug or "trade").strip()) or "trade"
    return f"trade-{safe}.xlsx"


def trade_order_attachment_filename() -> str:
    return "trade-order.xlsx"


def load_public_trade_rows_for_export(
    session: Session,
    *,
    user_id: int,
    q: str | None = None,
    set_code: str | None = None,
    rarity: str | None = None,
    sort: str = "set_code",
    sort_dir: str = "asc",
) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    total = None
    while total is None or offset < total:
        page, total = list_public_trade_items(
            session,
            user_id=user_id,
            q=q,
            set_code=set_code,
            rarity=rarity,
            sort=sort,
            sort_dir=sort_dir,
            limit=_PAGE_SIZE,
            offset=offset,
        )
        rows.extend(page)
        if not page:
            break
        offset += len(page)
    return rows


def write_trade_xlsx(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Trade"
    ws.append(list(TRADE_HEADERS))
    for row in rows:
        ws.append(
            [
                row.get("card_name") or "",
                row.get("set_code") or "",
                row.get("set_name") or "",
                row.get("rarity_display") or row.get("rarity_code") or "",
                row.get("edition") or "",
                row.get("condition") or "",
                row.get("trade_quantity") if row.get("trade_quantity") is not None else "",
                row.get("sell_price") if row.get("sell_price") is not None else "",
            ]
        )
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def write_trade_order_xlsx(lines: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Order"
    ws.append(list(TRADE_ORDER_HEADERS))
    for line in lines:
        ws.append(
            [
                line.get("card_name") or "",
                line.get("set_code") or "",
                line.get("set_name") or "",
                line.get("rarity_display") or line.get("rarity_code") or "",
                line.get("condition") or "",
                line.get("quantity") if line.get("quantity") is not None else "",
                line.get("list_price") if line.get("list_price") is not None else "",
                line.get("offer_price") if line.get("offer_price") is not None else "",
                line.get("comment") or "",
            ]
        )
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def export_public_trade_xlsx(
    session: Session,
    *,
    user_id: int,
    slug: str,
    q: str | None = None,
    set_code: str | None = None,
    rarity: str | None = None,
    sort: str = "set_code",
    sort_dir: str = "asc",
) -> tuple[bytes, str, str]:
    rows = load_public_trade_rows_for_export(
        session,
        user_id=user_id,
        q=q,
        set_code=set_code,
        rarity=rarity,
        sort=sort,
        sort_dir=sort_dir,
    )
    content = write_trade_xlsx(rows)
    return content, XLSX_MEDIA_TYPE, trade_export_filename(slug)
