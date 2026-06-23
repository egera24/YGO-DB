"""Job 3: scrape Cardmarket product detail pages for prices."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ygo_app.cardmarket.card_details_scrape import run_card_details_scrape
from ygo_app.cardmarket.expansion_list_scrape import fetch_expansion_list
from ygo_app.cardmarket.expansion_seed import load_seed_codes
from ygo_app.cardmarket.incremental import IncrementalConflictError, prepare_incremental_plan
from ygo_app.cardmarket.artifact_io import load_json_list
from ygo_app.cardmarket.paths import CARDMARKET_CARD_LIST_PATH, CARDMARKET_EXPANSION_LIST_PATH
from ygo_app.cardmarket.scrape_cli import (
    add_http_scrape_args,
    apply_polite_args,
    resolve_backend_from_args,
    validate_headed_args,
)
from ygo_app.cardmarket.scrape_session import prepare_scrape_session, scrape_session_context
from ygo_app.yugipedia.scrape_progress import log_line


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

    try:
        with scrape_session_context(result) as session:
            expansion_ids = None
            purge_card_ids = None
            merge_output = False
            skip_existing = False
            if args.incremental:
                stored = load_json_list(CARDMARKET_EXPANSION_LIST_PATH)
                live = fetch_expansion_list(session)
                plan = prepare_incremental_plan(stored, live, seed_codes=load_seed_codes())
                expansion_ids = plan.scrape_ids
                merge_output = True
                skip_existing = True
                if plan.purge_expansion_ids:
                    from ygo_app.cardmarket.incremental import card_ids_for_expansion_ids

                    existing_cards = load_json_list(args.input)
                    purge_card_ids = card_ids_for_expansion_ids(
                        existing_cards, plan.purge_expansion_ids
                    )
                if not expansion_ids:
                    log_line("[DETAILS] incremental: no new expansions to scrape")
                    return 0

            run_card_details_scrape(
                input_path=args.input,
                session=session,
                resume=args.resume,
                limit=args.limit,
                fast=args.fast,
                accept_rate_limit_risk=args.i_accept_rate_limit_risk,
                expansion_ids=expansion_ids,
                skip_existing=skip_existing,
                merge_output=merge_output,
                purge_card_ids=purge_card_ids,
            )
        return 0
    except IncrementalConflictError as exc:
        log_line(f"[DETAILS] conflict: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
