"""Job 1: scrape Cardmarket TCG expansion list."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ygo_app.cardmarket.artifact_io import load_json_list, save_json
from ygo_app.cardmarket.expansion_list_scrape import fetch_expansion_list, run_expansion_list_scrape
from ygo_app.cardmarket.expansion_seed import load_seed_codes
from ygo_app.cardmarket.incremental import (
    IncrementalConflictError,
    merge_expansion_lists,
    prepare_incremental_plan,
)
from ygo_app.cardmarket.paths import CARDMARKET_EXPANSION_LIST_PATH
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
            if args.incremental:
                if not args.output.is_file():
                    raise FileNotFoundError(
                        f"Incremental mode requires existing expansion list: {args.output}"
                    )
                stored = load_json_list(args.output)
                live = fetch_expansion_list(session)
                prepare_incremental_plan(stored, live, seed_codes=load_seed_codes())
                merged = merge_expansion_lists(stored, live)
                save_json(args.output, merged)
                log_line(f"[EXPANSIONS] incremental merge wrote {len(merged)} expansions")
            else:
                run_expansion_list_scrape(output=args.output, session=session)
        return 0
    except (IncrementalConflictError, FileNotFoundError) as exc:
        log_line(f"[EXPANSIONS] error: {exc}")
        return 1


def main(argv: list[str] | None = None) -> int:
    return run_job_logged(Path(__file__).stem, lambda: _run(argv))


if __name__ == "__main__":
    sys.exit(main())
