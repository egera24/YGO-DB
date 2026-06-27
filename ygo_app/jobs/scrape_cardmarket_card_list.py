"""Job 2: scrape Cardmarket card lists for all TCG expansions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ygo_app.cardmarket.artifact_io import load_json_list
from ygo_app.cardmarket.card_list_consistency import CardListConsistencyError
from ygo_app.cardmarket.card_list_scrape import run_card_list_scrape
from ygo_app.cardmarket.card_list_validate import CardListValidationError
from ygo_app.cardmarket.catalog_consistency import (
    CardListCoverageError,
    audit_card_list_coverage,
    gap_expansion_ids,
)
from ygo_app.cardmarket.expansion_list_scrape import fetch_expansion_list
from ygo_app.cardmarket.incremental import (
    IncrementalConflictError,
    merge_expansion_lists,
    prepare_incremental_plan,
)
from ygo_app.cardmarket.paths import (
    CARDMARKET_EMPTY_EXPANSIONS_PATH,
    CARDMARKET_REJECTED_EXPANSIONS_PATH,
    card_list_path,
    expansion_list_path,
)
from ygo_app.cardmarket.scrape_cli import (
    add_http_scrape_args,
    apply_polite_args,
    resolve_backend_from_args,
    validate_headed_args,
)
from ygo_app.cardmarket.scrape_session import prepare_scrape_session, scrape_session_context
from ygo_app.cardmarket.scrape_state import (
    find_latest_card_list,
    load_scrape_state,
    resolve_card_list_file,
    resolve_expansion_list_file,
    today_run_date,
)
from ygo_app.job_logging import run_job_logged
from ygo_app.yugipedia.scrape_progress import log_line


def _resolve_load_mode(args: argparse.Namespace) -> str:
    if args.full:
        return "full"
    if args.incremental:
        return "incremental"
    return "full"


def _run(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Cardmarket expansion product lists")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true", help="Full card list scrape for today's run")
    mode.add_argument(
        "--incremental",
        action="store_true",
        help="Scrape only expansions new since the previous dated run",
    )
    parser.add_argument(
        "--only-gaps",
        action="store_true",
        help="Scrape only expansions missing from cards/empty/rejected (coverage audit)",
    )
    add_http_scrape_args(parser, include_incremental=False)
    args = parser.parse_args(argv)
    apply_polite_args(args)
    validate_headed_args(args, parser)

    today = today_run_date()
    state = load_scrape_state()
    latest_card = find_latest_card_list()
    if latest_card and latest_card[0] == today and not args.resume and not args.only_gaps:
        if not args.full and not args.incremental:
            log_line(f"[CARD_LIST] same-day skip: card_list_{today}.json already exists")
            return 0
    if latest_card and latest_card[0] != today and not args.full and not args.incremental:
        if not args.only_gaps and not args.resume:
            parser.error(
                f"Previous card list is dated {latest_card[0]}; pass --full or --incremental"
            )

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
        interactive=not args.no_interactive,
    )
    if isinstance(result, int):
        return result

    load_mode = _resolve_load_mode(args)
    input_path = resolve_expansion_list_file(state) if state else expansion_list_path(today)
    if args.resume and state:
        output_path = resolve_card_list_file(state)
    else:
        output_path = card_list_path(today)

    try:
        with scrape_session_context(result) as session:
            expansion_filter = None
            purge_ids = None
            if args.only_gaps:
                expansion_list = load_json_list(input_path)
                card_list = load_json_list(output_path) if output_path.is_file() else []
                empty_expansions = (
                    load_json_list(CARDMARKET_EMPTY_EXPANSIONS_PATH)
                    if CARDMARKET_EMPTY_EXPANSIONS_PATH.is_file()
                    else []
                )
                rejected_expansions = (
                    load_json_list(CARDMARKET_REJECTED_EXPANSIONS_PATH)
                    if CARDMARKET_REJECTED_EXPANSIONS_PATH.is_file()
                    else []
                )
                report = audit_card_list_coverage(
                    expansion_list=expansion_list,
                    card_list=card_list,
                    empty_expansions=empty_expansions,
                    rejected_expansions=rejected_expansions,
                )
                expansion_filter = gap_expansion_ids(report)
                if not expansion_filter:
                    log_line("[CARD_LIST] --only-gaps: no expansion gaps to scrape")
                    return 0 if report.ok else 1
                log_line(
                    f"[CARD_LIST] --only-gaps: scraping {len(expansion_filter)} expansion(s)"
                )
            elif args.incremental and state:
                stored = load_json_list(input_path)
                live = fetch_expansion_list(session)
                plan = prepare_incremental_plan(stored, live)
                from ygo_app.cardmarket.artifact_io import save_json_atomic

                merged = merge_expansion_lists(stored, live)
                save_json_atomic(input_path, merged)
                expansion_filter = plan.scrape_ids
                purge_ids = plan.purge_expansion_ids
                if not expansion_filter and not purge_ids:
                    log_line("[CARD_LIST] incremental: no new expansions to scrape")
                    return 0

            run_card_list_scrape(
                input_path=input_path,
                output_path=output_path,
                session=session,
                resume=args.resume,
                limit=args.limit,
                load_mode=load_mode,
                expansion_filter=expansion_filter,
                purge_expansion_ids=purge_ids,
                skip_same_day=not args.full and not args.incremental and not args.only_gaps,
            )
        return 0
    except CardListCoverageError as exc:
        log_line(f"[CARD_LIST] coverage: {exc}")
        return 1
    except (CardListConsistencyError, CardListValidationError) as exc:
        log_line(f"[CARD_LIST] consistency: {exc}")
        return 1
    except IncrementalConflictError as exc:
        log_line(f"[CARD_LIST] conflict: {exc}")
        return 1


def main(argv: list[str] | None = None) -> int:
    return run_job_logged(Path(__file__).stem, lambda: _run(argv))


if __name__ == "__main__":
    sys.exit(main())
