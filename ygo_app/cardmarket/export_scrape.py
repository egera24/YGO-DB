"""Export-only Cardmarket scrape: local cache → JSON file."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from ygo_app.cardmarket.browser_client import (
    close_browser_session,
    configure_browser_session,
    run_cf_login,
)
from ygo_app.cardmarket.browser_cookies import storage_has_cf_clearance
from ygo_app.cardmarket.catalog_source import load_catalog_printings
from ygo_app.cardmarket.constants import DEFAULT_MAX_AGE_DAYS, FetchBackend
from ygo_app.cardmarket.export_schema import build_export_payload, row_from_db, save_export
from ygo_app.cardmarket.http_client import default_fetch_backend, resolve_scrape_settings
from ygo_app.cardmarket.local_store import clear_local_cache, get_local_session
from ygo_app.cardmarket.market_prices import all_market_price_rows, discover_printings, sync_prices
from ygo_app.cardmarket.paths import (
    CARDMARKET_BROWSER_STATE_PATH,
    CARDMARKET_CACHE_DB,
    CARDMARKET_PRICES_PATH,
    DEFAULT_CATALOG_PATH,
)
from ygo_app.yugipedia.scrape_progress import log_line


def rows_to_export_dicts(session: Session) -> list[dict]:
    out: list[dict] = []
    for row in all_market_price_rows(session):
        out.append(
            row_from_db(
                set_code=row.set_code,
                rarity_code=row.rarity_code,
                cardmarket_product_id=row.cardmarket_product_id,
                cardmarket_url=row.cardmarket_url,
                low_price=row.low_price,
                avg_price=row.avg_price,
                trend_price=row.trend_price,
                discovery_status=row.discovery_status,
            )
        )
    return out


def run_export_scrape(
    *,
    output: Path = CARDMARKET_PRICES_PATH,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    cache_path: Path = CARDMARKET_CACHE_DB,
    full: bool = False,
    discover_only: bool = False,
    prices_only: bool = False,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    workers: int = 8,
    limit: int | None = None,
    backend: FetchBackend | None = None,
    use_browser: bool = False,
    headed: bool = False,
    cf_login: bool = False,
    browser_channel: str | None = None,
    price_rps: float | None = None,
    discovery_rps: float | None = None,
) -> int:
    if not catalog_path.is_file():
        raise FileNotFoundError(
            f"Catalog JSON not found: {catalog_path}. "
            "Run Yugipedia scrape/import first or pass --catalog."
        )

    if cf_login:
        channel = browser_channel or "chrome"
        return run_cf_login(
            storage_path=CARDMARKET_BROWSER_STATE_PATH,
            browser_channel=channel,  # type: ignore[arg-type]
        )

    effective_backend = backend
    if use_browser and effective_backend is None:
        effective_backend = "playwright"
    if effective_backend is None:
        effective_backend = default_fetch_backend()

    effective_workers, eff_discovery_rps, eff_price_rps, backend_label = resolve_scrape_settings(
        backend=effective_backend,
        use_browser=use_browser,
        workers=workers,
        price_rps=price_rps,
        discovery_rps=discovery_rps,
    )
    if backend_label == "playwright":
        configure_browser_session(
            headed=headed,
            storage_path=CARDMARKET_BROWSER_STATE_PATH,
            browser_channel=browser_channel or ("chrome" if headed else None),  # type: ignore[arg-type]
        )

    if backend_label in ("curl_cffi", "cloudscraper"):
        if storage_has_cf_clearance(CARDMARKET_BROWSER_STATE_PATH):
            log_line(f"[COOKIES] will reuse cf_clearance from {CARDMARKET_BROWSER_STATE_PATH}")
        else:
            log_line(
                "[WARN] No cf_clearance cookies found. If you get HTTP 403, run: "
                "python -m ygo_app.jobs.scrape_cardmarket_prices --cf-login"
            )

    log_line(
        f"[CARDMARKET] backend={backend_label} workers={effective_workers} "
        f"discovery_rps={eff_discovery_rps} price_rps={eff_price_rps}"
        + (" headed" if headed and backend_label == "playwright" else "")
    )

    catalog = load_catalog_printings(None, catalog_path=catalog_path)
    session = get_local_session(cache_path)
    try:
        if full:
            log_line("[CACHE] clearing local price cache (--full)")
            clear_local_cache(session)

        if not prices_only:
            log_line("[PHASE] discovery")
            disc_stats = discover_printings(
                session,
                full=full,
                limit=limit,
                catalog=catalog,
                backend=backend_label,
                discovery_rps=eff_discovery_rps,
            )
            log_line(
                f"[DISCOVER] matched={disc_stats['matched']} "
                f"unmatched={disc_stats['unmatched']} expansions={disc_stats['expansions']}"
            )

        if not discover_only:
            log_line("[PHASE] price sync")
            effective_max_age = 0 if full else max_age_days
            price_stats = sync_prices(
                session,
                full=full or effective_max_age == 0,
                max_age_days=effective_max_age,
                limit=limit,
                workers=effective_workers,
                backend=backend_label,
                price_rps=eff_price_rps,
            )
            log_line(
                f"[PRICES] total={price_stats['total']} "
                f"updated={price_stats['updated']} failed={price_stats['failed']}"
            )

        payload = build_export_payload(rows_to_export_dicts(session))
        save_export(output, payload)
        log_line(
            f"[EXPORT] wrote {output} "
            f"(rows={payload['stats']['total']} with_prices={payload['stats']['with_prices']})"
        )
        return 0
    finally:
        session.close()
        if backend_label == "playwright":
            close_browser_session()
