"""Job 2: scrape Cardmarket card lists for all TCG expansions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ygo_app.cardmarket.card_list_scrape import run_card_list_scrape
from ygo_app.cardmarket.paths import (
    CARDMARKET_CARD_LIST_PATH,
    CARDMARKET_EXPANSION_LIST_PATH,
)
from ygo_app.cardmarket.scrape_cli import (
    add_http_scrape_args,
    resolve_backend_from_args,
    validate_headed_args,
)
from ygo_app.cardmarket.scrape_session import prepare_scrape_session, scrape_session_context


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Cardmarket expansion product lists")
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=CARDMARKET_EXPANSION_LIST_PATH,
        help="Expansion list JSON from job 1",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=CARDMARKET_CARD_LIST_PATH,
        help="Output card list JSON",
    )
    parser.add_argument(
        "--no-update-seed",
        action="store_true",
        help="Skip regenerating expansion_seed.json after completion",
    )
    add_http_scrape_args(parser)
    args = parser.parse_args(argv)
    validate_headed_args(args, parser)

    result = prepare_scrape_session(
        backend=resolve_backend_from_args(args),
        use_browser=args.browser,
        headed=args.headed,
        cf_login=args.cf_login,
        browser_channel=args.browser_channel,
        browser_profiles=args.browser_profiles,
        workers=args.workers,
        price_rps=args.rps,
        discovery_rps=args.discovery_rps,
    )
    if isinstance(result, int):
        return result

    with scrape_session_context(result) as session:
        run_card_list_scrape(
            input_path=args.input,
            output_path=args.output,
            session=session,
            resume=args.resume,
            limit=args.limit,
            update_seed=not args.no_update_seed,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
