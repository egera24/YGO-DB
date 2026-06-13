"""DB helpers for printing market prices."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from ygo_app.models import Printing, PrintingMarketPrice


def load_market_prices(
    session: Session,
    keys: list[tuple[str, str]],
) -> dict[tuple[str, str], PrintingMarketPrice]:
    if not keys:
        return {}
    rows = session.scalars(
        select(PrintingMarketPrice).where(
            tuple_(PrintingMarketPrice.set_code, PrintingMarketPrice.rarity_code).in_(keys)
        )
    ).all()
    return {(row.set_code, row.rarity_code): row for row in rows}


def attach_market_prices_to_printings(session: Session, printings: list[Printing]) -> None:
    keys = [(p.set_code, p.set_rarity_code) for p in printings]
    prices = load_market_prices(session, keys)
    for printing in printings:
        row = prices.get((printing.set_code, printing.set_rarity_code))
        if row:
            printing.low_price = row.low_price
            printing.avg_price = row.avg_price
            printing.trend_price = row.trend_price
            printing.price_currency = row.currency
            printing.prices_updated_at = row.updated_at
        else:
            printing.low_price = None
            printing.avg_price = None
            printing.trend_price = None
            printing.price_currency = None
            printing.prices_updated_at = None


def distinct_catalog_printings(session: Session) -> list[tuple[str, str, str | None]]:
    rows = session.execute(
        select(Printing.set_code, Printing.set_rarity_code, Printing.set_rarity).distinct()
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def upsert_market_price(
    session: Session,
    *,
    set_code: str,
    rarity_code: str,
    cardmarket_product_id: int | None = None,
    cardmarket_url: str | None = None,
    low_price: float | None = None,
    avg_price: float | None = None,
    trend_price: float | None = None,
    discovery_status: str | None = None,
    update_prices: bool = False,
) -> PrintingMarketPrice:
    row = session.get(PrintingMarketPrice, {"set_code": set_code, "rarity_code": rarity_code})
    if row is None:
        row = PrintingMarketPrice(set_code=set_code, rarity_code=rarity_code)
        session.add(row)

    if cardmarket_product_id is not None:
        row.cardmarket_product_id = cardmarket_product_id
    if cardmarket_url is not None:
        row.cardmarket_url = cardmarket_url
    if discovery_status is not None:
        row.discovery_status = discovery_status
    if update_prices:
        row.low_price = low_price
        row.avg_price = avg_price
        row.trend_price = trend_price
        row.updated_at = datetime.utcnow()
    row.currency = row.currency or "EUR"
    return row
