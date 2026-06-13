"""Scrape Cardmarket LOW/AVG/TREND prices for catalog printings."""

from __future__ import annotations

import argparse
import sys

from ygo_app.cardmarket.constants import DEFAULT_MAX_AGE_DAYS, DEFAULT_WORKERS
from ygo_app.cardmarket.market_prices import discover_printings, sync_prices
from ygo_app.database import SessionLocal, init_db
from ygo_app.yugipedia.scrape_progress import log_line


def run(
    *,
    full: bool = False,
    discover_only: bool = False,
    prices_only: bool = False,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    workers: int = DEFAULT_WORKERS,
    limit: int | None = None,
) -> int:
    init_db()
    session = SessionLocal()
    try:
        if not prices_only:
            log_line("[PHASE] discovery")
            disc_stats = discover_printings(session, full=full, limit=limit)
            log_line(
                f"[DISCOVER] matched={disc_stats['matched']} "
                f"unmatched={disc_stats['unmatched']} expansions={disc_stats['expansions']}"
            )

        if not discover_only:
            log_line("[PHASE] price sync")
            if full:
                max_age_days = 0
            price_stats = sync_prices(
                session,
                full=full or max_age_days == 0,
                max_age_days=max_age_days,
                limit=limit,
                workers=workers,
            )
            log_line(
                f"[PRICES] total={price_stats['total']} "
                f"updated={price_stats['updated']} failed={price_stats['failed']}"
            )

        return 0
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Cardmarket printing prices")
    parser.add_argument("--full", action="store_true", help="Re-discover and refresh all prices")
    parser.add_argument("--discover-only", action="store_true", help="Only run discovery phase")
    parser.add_argument("--prices-only", action="store_true", help="Only refresh prices")
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        help="Incremental: refresh prices older than N days (default 7)",
    )
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Parallel workers")
    parser.add_argument("--limit", type=int, default=None, help="Cap printings processed (testing)")
    args = parser.parse_args(argv)

    if args.discover_only and args.prices_only:
        parser.error("Cannot use --discover-only and --prices-only together")

    return run(
        full=args.full,
        discover_only=args.discover_only,
        prices_only=args.prices_only,
        max_age_days=args.max_age_days,
        workers=args.workers,
        limit=args.limit,
    )


if __name__ == "__main__":
    sys.exit(main())
