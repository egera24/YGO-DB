"""Scrape Cardmarket LOW/AVG/TREND prices locally and write JSON export.

Local-only (residential IP). Does not connect to Neon.
Import into Postgres: python -m ygo_app.jobs.import_cardmarket_prices
Upload to R2: python -m ygo_app.jobs.upload_cardmarket_prices
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ygo_app.cardmarket.constants import DEFAULT_MAX_AGE_DAYS, DEFAULT_WORKERS
from ygo_app.cardmarket.export_scrape import run_export_scrape
from ygo_app.cardmarket.paths import CARDMARKET_PRICES_PATH, DEFAULT_CATALOG_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scrape Cardmarket prices locally and export JSON (no database)"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=CARDMARKET_PRICES_PATH,
        help="Output JSON path (default: data/catalog/cardmarket_prices.json)",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG_PATH,
        help="Yugipedia catalog JSON for printing list (default: yugipedia_all_cards.json)",
    )
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
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Use Playwright Chromium instead of cloudscraper (slower, fewer 403/429 issues)",
    )
    args = parser.parse_args(argv)

    if args.discover_only and args.prices_only:
        parser.error("Cannot use --discover-only and --prices-only together")

    return run_export_scrape(
        output=args.output,
        catalog_path=args.catalog,
        full=args.full,
        discover_only=args.discover_only,
        prices_only=args.prices_only,
        max_age_days=args.max_age_days,
        workers=args.workers,
        limit=args.limit,
        use_browser=args.browser,
    )


if __name__ == "__main__":
    sys.exit(main())
