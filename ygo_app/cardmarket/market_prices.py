"""DB helpers for printing market prices (SCD Type 2)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from ygo_app.models import Printing, PrintingMarketPrice

_PREFETCH_SENTINEL = object()


def market_price_or_zero(value: float | None) -> float:
    return float(value) if value is not None else 0.0


def resolve_sell_price(
    stored_sell: float | None,
    market_trend: float | None,
) -> float:
    if stored_sell is not None:
        return float(stored_sell)
    return market_price_or_zero(market_trend)


def market_prices_tuple(
    row: PrintingMarketPrice | None,
) -> tuple[float, float, float]:
    if row is None:
        return 0.0, 0.0, 0.0
    return (
        market_price_or_zero(row.low_price),
        market_price_or_zero(row.avg_price),
        market_price_or_zero(row.trend_price),
    )


def _prices_equal(
    current: PrintingMarketPrice,
    *,
    low_price: float | None,
    avg_price: float | None,
    trend_price: float | None,
) -> bool:
    return (
        current.low_price == low_price
        and current.avg_price == avg_price
        and current.trend_price == trend_price
    )


def get_current_market_price(
    session: Session,
    set_code: str,
    rarity_code: str,
) -> PrintingMarketPrice | None:
    return session.scalars(
        select(PrintingMarketPrice).where(
            PrintingMarketPrice.set_code == set_code,
            PrintingMarketPrice.rarity_code == rarity_code,
            PrintingMarketPrice.is_current.is_(True),
        )
    ).first()


def load_market_prices(
    session: Session,
    keys: list[tuple[str, str]],
) -> dict[tuple[str, str], PrintingMarketPrice]:
    if not keys:
        return {}
    rows = session.scalars(
        select(PrintingMarketPrice).where(
            PrintingMarketPrice.is_current.is_(True),
            tuple_(PrintingMarketPrice.set_code, PrintingMarketPrice.rarity_code).in_(keys),
        )
    ).all()
    return {(row.set_code, row.rarity_code): row for row in rows}


def load_all_current_market_prices(
    session: Session,
) -> dict[tuple[str, str], PrintingMarketPrice]:
    rows = session.scalars(
        select(PrintingMarketPrice).where(PrintingMarketPrice.is_current.is_(True))
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
            printing.prices_updated_at = row.valid_from
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


def apply_scd_price_update(
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
    source_run_id: str | None = None,
    update_prices: bool = False,
    current: PrintingMarketPrice | None | object = _PREFETCH_SENTINEL,
) -> tuple[PrintingMarketPrice | None, str]:
    """Apply SCD Type 2 update. Returns (current_row_or_none, action)."""
    now = datetime.utcnow()
    if current is _PREFETCH_SENTINEL:
        current = get_current_market_price(session, set_code, rarity_code)

    if current is None:
        row = PrintingMarketPrice(
            set_code=set_code,
            rarity_code=rarity_code,
            cardmarket_product_id=cardmarket_product_id,
            cardmarket_url=cardmarket_url,
            low_price=low_price if update_prices else None,
            avg_price=avg_price if update_prices else None,
            trend_price=trend_price if update_prices else None,
            currency="EUR",
            discovery_status=discovery_status,
            valid_from=now,
            valid_to=None,
            is_current=True,
            source_run_id=source_run_id,
        )
        session.add(row)
        return row, "inserted"

    changed_meta = False
    if cardmarket_product_id is not None and current.cardmarket_product_id != cardmarket_product_id:
        changed_meta = True
    if cardmarket_url is not None and current.cardmarket_url != cardmarket_url:
        changed_meta = True
    if discovery_status is not None and current.discovery_status != discovery_status:
        changed_meta = True

    price_changed = update_prices and not _prices_equal(
        current,
        low_price=low_price,
        avg_price=avg_price,
        trend_price=trend_price,
    )

    if not price_changed and not changed_meta:
        return current, "unchanged"

    if price_changed:
        current.valid_to = now
        current.is_current = False
        row = PrintingMarketPrice(
            set_code=set_code,
            rarity_code=rarity_code,
            cardmarket_product_id=cardmarket_product_id or current.cardmarket_product_id,
            cardmarket_url=cardmarket_url or current.cardmarket_url,
            low_price=low_price,
            avg_price=avg_price,
            trend_price=trend_price,
            currency=current.currency or "EUR",
            discovery_status=discovery_status or current.discovery_status,
            valid_from=now,
            valid_to=None,
            is_current=True,
            source_run_id=source_run_id,
        )
        session.add(row)
        return row, "updated"

    if cardmarket_product_id is not None:
        current.cardmarket_product_id = cardmarket_product_id
    if cardmarket_url is not None:
        current.cardmarket_url = cardmarket_url
    if discovery_status is not None:
        current.discovery_status = discovery_status
    if source_run_id is not None:
        current.source_run_id = source_run_id
    return current, "metadata_updated"


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
    source_run_id: str | None = None,
) -> PrintingMarketPrice:
    row, _action = apply_scd_price_update(
        session,
        set_code=set_code,
        rarity_code=rarity_code,
        cardmarket_product_id=cardmarket_product_id,
        cardmarket_url=cardmarket_url,
        low_price=low_price,
        avg_price=avg_price,
        trend_price=trend_price,
        discovery_status=discovery_status,
        source_run_id=source_run_id,
        update_prices=update_prices,
    )
    assert row is not None
    return row
