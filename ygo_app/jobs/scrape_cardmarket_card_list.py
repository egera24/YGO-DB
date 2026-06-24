"""Job 2: scrape Cardmarket card lists for all TCG expansions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ygo_app.cardmarket.card_list_scrape import run_card_list_scrape
from ygo_app.cardmarket.expansion_list_scrape import fetch_expansion_list
from ygo_app.cardmarket.expansion_seed import load_seed_codes
from ygo_app.cardmarket.incremental import (
    IncrementalConflictError,
    merge_expansion_lists,
    prepare_incremental_plan,
)
from ygo_app.cardmarket.artifact_io import load_json_list, save_json
from ygo_app.cardmarket.paths import (
    CARDMARKET_CARD_LIST_PATH,
    CARDMARKET_EXPANSION_LIST_PATH,
)
from ygo_app.cardmarket.scrape_cli import (
    add_http_scrape_args,
    apply_polite_args,
    resolve_backend_from_args,
    validate_headed_args,
)
from ygo_app.cardmarket.scrape_session import prepare_scrape_session, scrape_session_context
from ygo_app.job_logging import run_job_logged
from ygo_app.yugipedia.scrape_progress import log_line


def _run(argv: list[str] | None) -> int:
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
            expansion_filter = None
            purge_ids = None
            if args.incremental:
                stored = load_json_list(args.input)
                live = fetch_expansion_list(session)
                plan = prepare_incremental_plan(stored, live, seed_codes=load_seed_codes())
                merged_expansions = merge_expansion_lists(stored, live)
                save_json(args.input, merged_expansions)
                expansion_filter = plan.scrape_ids
                purge_ids = plan.purge_expansion_ids
                if not expansion_filter:
                    log_line("[CARD_LIST] incremental: no new expansions to scrape")
                    return 0

            run_card_list_scrape(
                input_path=args.input,
                output_path=args.output,
                session=session,
                resume=args.resume,
                limit=args.limit,
                update_seed=not args.no_update_seed,
                expansion_filter=expansion_filter,
                purge_expansion_ids=purge_ids,
            )
        return 0
    except IncrementalConflictError as exc:
        log_line(f"[CARD_LIST] conflict: {exc}")
        return 1


def main(argv: list[str] | None = None) -> int:
    return run_job_logged(Path(__file__).stem, lambda: _run(argv))


if __name__ == "__main__":
    sys.exit(main())
