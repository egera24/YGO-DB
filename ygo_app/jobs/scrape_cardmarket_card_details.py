"""Job 3: scrape Cardmarket product detail pages for prices."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ygo_app.cardmarket.card_details_scrape import run_card_details_scrape
from ygo_app.cardmarket.paths import CARDMARKET_CARD_LIST_PATH
from ygo_app.cardmarket.scrape_cli import (
    add_http_scrape_args,
    apply_polite_args,
    resolve_backend_from_args,
    validate_headed_args,
)
from ygo_app.cardmarket.scrape_session import prepare_scrape_session, scrape_session_context


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Cardmarket card detail prices")
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=CARDMARKET_CARD_LIST_PATH,
        help="Card list JSON from job 2",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Legacy fast preset (20 workers / 8 rps — requires --i-accept-rate-limit-risk)",
    )
    parser.add_argument(
        "--i-accept-rate-limit-risk",
        action="store_true",
        help="Acknowledge rate-limit risk when using --fast",
    )
    add_http_scrape_args(parser)
    args = parser.parse_args(argv)
    apply_polite_args(args)
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
        run_card_details_scrape(
            input_path=args.input,
            session=session,
            resume=args.resume,
            limit=args.limit,
            fast=args.fast,
            accept_rate_limit_risk=args.i_accept_rate_limit_risk,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
