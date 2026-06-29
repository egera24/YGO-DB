"""Job 4: export Yugipedia-matched prices from Cardmarket details JSON."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ygo_app.cardmarket.details_export import export_prices_from_details
from ygo_app.cardmarket.paths import (
    CARDMARKET_CARD_DETAILS_PATH,
    CARDMARKET_PRICES_PATH,
    DEFAULT_CATALOG_PATH,
)
from ygo_app.cardmarket.scrape_state import load_scrape_state, resolve_card_details_file
from ygo_app.job_logging import run_job_logged


def _default_details_path() -> Path:
    state = load_scrape_state()
    if state:
        dated = resolve_card_details_file(state)
        if dated.is_file():
            return dated
    return CARDMARKET_CARD_DETAILS_PATH


def _run(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(
        description="Join Cardmarket details with Yugipedia catalog → cardmarket_prices.json"
    )
    parser.add_argument(
        "--details",
        type=Path,
        default=_default_details_path(),
        help="Card details JSON from job 3",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG_PATH,
        help="Yugipedia catalog JSON",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=CARDMARKET_PRICES_PATH,
        help="Output export JSON",
    )
    parser.add_argument("--limit", type=int, default=None, help="Cap catalog printings (testing)")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Validate details for duplicate match keys before export",
    )
    args = parser.parse_args(argv)

    export_prices_from_details(
        details_path=args.details,
        catalog_path=args.catalog,
        output_path=args.output,
        limit=args.limit,
        validate=args.incremental,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_job_logged(Path(__file__).stem, lambda: _run(argv))


if __name__ == "__main__":
    sys.exit(main())
