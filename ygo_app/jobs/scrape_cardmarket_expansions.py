"""Job 1: scrape Cardmarket TCG expansion list."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ygo_app.cardmarket.expansion_list_scrape import run_expansion_list_scrape
from ygo_app.cardmarket.paths import CARDMARKET_EXPANSION_LIST_PATH
from ygo_app.cardmarket.scrape_cli import (
    add_http_scrape_args,
    resolve_backend_from_args,
    validate_headed_args,
)
from ygo_app.cardmarket.scrape_session import prepare_scrape_session, scrape_session_context


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Cardmarket TCG expansion list")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=CARDMARKET_EXPANSION_LIST_PATH,
        help="Output JSON path",
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
        workers=args.workers,
        price_rps=args.rps,
        discovery_rps=args.discovery_rps,
    )
    if isinstance(result, int):
        return result

    with scrape_session_context(result) as session:
        run_expansion_list_scrape(output=args.output, session=session)
    return 0


if __name__ == "__main__":
    sys.exit(main())
