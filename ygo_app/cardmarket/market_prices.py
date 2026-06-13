"""DB helpers for printing market prices."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import or_, select, tuple_
from sqlalchemy.orm import Session

from ygo_app.cardmarket.constants import (
    DISCOVERY_ERROR,
    DISCOVERY_MATCHED,
    DISCOVERY_UNMATCHED,
    FetchBackend,
)
from ygo_app.cardmarket.matching import build_cardmarket_index, printing_match_key
from ygo_app.models import CardmarketExpansion, Printing, PrintingMarketPrice


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


def select_prices_to_refresh(
    session: Session,
    *,
    full: bool = False,
    max_age_days: int = 7,
    limit: int | None = None,
) -> list[PrintingMarketPrice]:
    query = select(PrintingMarketPrice).where(
        PrintingMarketPrice.cardmarket_url.isnot(None),
        PrintingMarketPrice.discovery_status == DISCOVERY_MATCHED,
    )
    if not full:
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        query = query.where(
            or_(
                PrintingMarketPrice.updated_at.is_(None),
                PrintingMarketPrice.updated_at < cutoff,
            )
        )
    query = query.order_by(PrintingMarketPrice.updated_at.asc().nullsfirst())
    if limit is not None:
        query = query.limit(limit)
    return list(session.scalars(query))


def discover_printings(
    session: Session,
    *,
    full: bool = False,
    limit: int | None = None,
    catalog: list[tuple[str, str, str | None]] | None = None,
    backend: FetchBackend = "cloudscraper",
    discovery_rps: float = 3.0,
) -> dict[str, int]:
    from ygo_app.cardmarket.expansions import refresh_expansion_cache, resolve_expansion_ids
    from ygo_app.cardmarket.http_client import AdaptiveRateLimiter, create_scraper, create_session_pool
    from ygo_app.cardmarket.product_list import scrape_expansion_products

    stats = {"matched": 0, "unmatched": 0, "expansions": 0}

    if catalog is None:
        catalog = distinct_catalog_printings(session)
    if limit is not None:
        catalog = catalog[:limit]

    pending: dict[tuple[str, str], tuple[str, str, str | None]] = {}
    expansion_codes: set[str] = set()
    for set_code, rarity_code, rarity_name in catalog:
        match_key = printing_match_key(set_code, rarity_name, rarity_code)
        if not match_key:
            continue
        pending[match_key] = (set_code, rarity_code, rarity_name)
        expansion_codes.add(match_key[0].split("-EN", 1)[0])

    if not pending:
        return stats

    if not full:
        existing = load_market_prices(session, [(sc, rc) for sc, rc, _ in catalog])
        pending = {
            key: val
            for key, val in pending.items()
            if existing.get((val[0], val[1])) is None
            or existing[(val[0], val[1])].discovery_status != DISCOVERY_MATCHED
        }
        expansion_codes = {key[0].split("-EN", 1)[0] for key in pending}

    if not pending:
        return stats

    refresh_expansion_cache(session, force=full, backend=backend, discovery_rps=discovery_rps)
    code_to_id = resolve_expansion_ids(
        session,
        expansion_codes,
        force_refresh=full,
        backend=backend,
        discovery_rps=discovery_rps,
    )

    scraper = create_scraper(0) if backend == "cloudscraper" else None
    rate_limiter = AdaptiveRateLimiter(discovery_rps)

    for exp_code, expansion_id in code_to_id.items():
        db_row = session.get(CardmarketExpansion, expansion_id)
        expansion_name = db_row.expansion_name if db_row else exp_code
        products = scrape_expansion_products(
            scraper,
            expansion_id,
            expansion_name,
            rate_limiter=rate_limiter,
            expansion_code=exp_code,
            backend=backend,
        )
        if products and db_row and not db_row.expansion_code:
            db_row.expansion_code = (products[0].get("expansion_code") or exp_code).upper()

        index = build_cardmarket_index(products)
        stats["expansions"] += 1
        prefix = f"{exp_code.upper()}-EN"

        for key, (set_code, rarity_code, _rarity_name) in list(pending.items()):
            if not key[0].startswith(prefix):
                continue
            product = index.get(key)
            if product:
                upsert_market_price(
                    session,
                    set_code=set_code,
                    rarity_code=rarity_code,
                    cardmarket_product_id=product.get("card_id"),
                    cardmarket_url=product.get("card_url"),
                    discovery_status=DISCOVERY_MATCHED,
                )
                stats["matched"] += 1
            else:
                upsert_market_price(
                    session,
                    set_code=set_code,
                    rarity_code=rarity_code,
                    discovery_status=DISCOVERY_UNMATCHED,
                )
                stats["unmatched"] += 1
            pending.pop(key, None)

        session.commit()

    for _key, (set_code, rarity_code, _name) in pending.items():
        upsert_market_price(
            session,
            set_code=set_code,
            rarity_code=rarity_code,
            discovery_status=DISCOVERY_ERROR,
        )
        stats["unmatched"] += 1
    session.commit()

    return stats


def sync_prices(
    session: Session,
    *,
    full: bool = False,
    max_age_days: int = 7,
    limit: int | None = None,
    workers: int = 8,
    backend: FetchBackend = "cloudscraper",
    price_rps: float = 4.0,
) -> dict[str, int]:
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from ygo_app.cardmarket.constants import RANDOM_JITTER
    from ygo_app.cardmarket.http_client import AdaptiveRateLimiter, create_session_pool, fetch_url
    from ygo_app.cardmarket.parsing import extract_price_data

    rows = select_prices_to_refresh(session, full=full, max_age_days=max_age_days, limit=limit)
    stats = {"total": len(rows), "updated": 0, "failed": 0}
    if not rows:
        return stats

    rate_limiter = AdaptiveRateLimiter(price_rps)
    session_pool = create_session_pool(backend, workers)
    lock = threading.Lock()

    def process_row(row: PrintingMarketPrice) -> tuple[str, str, dict[str, float | None] | None]:
        worker_id = threading.get_ident() % max(workers, 1)
        scraper = None
        if backend == "cloudscraper" and session_pool is not None:
            scraper, _ = session_pool.get_session(worker_id)
        elif backend == "curl_cffi" and session_pool is not None:
            scraper, _ = session_pool.get_session(worker_id)
        html, _error = fetch_url(
            scraper,
            row.cardmarket_url or "",
            backend=backend,
            rate_limiter=rate_limiter,
            jitter=RANDOM_JITTER,
            session_pool=session_pool,
            worker_id=worker_id,
        )
        if not html:
            return row.set_code, row.rarity_code, None
        return row.set_code, row.rarity_code, extract_price_data(html)

    def _has_any_price(prices: dict[str, float | None]) -> bool:
        return any(prices.get(k) is not None for k in ("low_price", "avg_price", "trend_price"))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(process_row, row) for row in rows]
        for future in as_completed(futures):
            set_code, rarity_code, prices = future.result()
            if not prices or not _has_any_price(prices):
                stats["failed"] += 1
                continue
            with lock:
                upsert_market_price(
                    session,
                    set_code=set_code,
                    rarity_code=rarity_code,
                    low_price=prices.get("low_price"),
                    avg_price=prices.get("avg_price"),
                    trend_price=prices.get("trend_price"),
                    update_prices=True,
                )
                stats["updated"] += 1
                if stats["updated"] % 50 == 0:
                    session.commit()

    session.commit()
    return stats


def all_market_price_rows(session: Session) -> list[PrintingMarketPrice]:
    return list(session.scalars(select(PrintingMarketPrice)))
