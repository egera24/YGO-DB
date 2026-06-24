"""Orchestrator: incremental Cardmarket scrape (new expansions only)."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from ygo_app.cardmarket.artifact_io import load_json_list, save_json
from ygo_app.cardmarket.card_details_scrape import run_card_details_scrape
from ygo_app.cardmarket.card_list_scrape import scrape_expansions
from ygo_app.cardmarket.details_export import export_prices_from_details, validate_export_match_keys
from ygo_app.cardmarket.expansion_list_scrape import fetch_expansion_list
from ygo_app.cardmarket.expansion_seed import load_seed_codes, regenerate_expansion_seed
from ygo_app.cardmarket.incremental import (
    IncrementalConflictError,
    card_ids_for_expansion_ids,
    merge_card_details,
    merge_card_lists,
    merge_expansion_lists,
    prepare_incremental_plan,
    raise_on_conflicts,
    validate_catalog_integrity,
)
from ygo_app.cardmarket.paths import (
    CARDMARKET_CARD_DETAILS_PATH,
    CARDMARKET_CARD_LIST_PATH,
    CARDMARKET_EXPANSION_LIST_PATH,
    CARDMARKET_INCREMENTAL_REPORT_PATH,
    CARDMARKET_PRICES_PATH,
    DEFAULT_CATALOG_PATH,
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

_REQUIRED_ARTIFACTS = (
    CARDMARKET_EXPANSION_LIST_PATH,
    CARDMARKET_CARD_LIST_PATH,
    CARDMARKET_CARD_DETAILS_PATH,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _require_artifacts() -> None:
    missing = [p for p in _REQUIRED_ARTIFACTS if not p.is_file()]
    if missing:
        paths = ", ".join(str(p) for p in missing)
        raise FileNotFoundError(
            f"Incremental mode requires a prior full scrape. Missing: {paths}. "
            "Run the full 4-step Cardmarket pipeline first."
        )


def run_incremental_scrape(
    *,
    session,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    output_prices_path: Path = CARDMARKET_PRICES_PATH,
    update_seed: bool = True,
) -> dict:
    """Execute incremental diff → scrape → merge → export. Returns report dict."""
    _require_artifacts()

    stored_expansions = load_json_list(CARDMARKET_EXPANSION_LIST_PATH)
    existing_cards = load_json_list(CARDMARKET_CARD_LIST_PATH)
    existing_details = load_json_list(CARDMARKET_CARD_DETAILS_PATH)

    live_expansions = fetch_expansion_list(session)
    seed_codes = load_seed_codes()
    plan = prepare_incremental_plan(stored_expansions, live_expansions, seed_codes=seed_codes)

    merged_expansion_list = merge_expansion_lists(stored_expansions, live_expansions)
    save_json(CARDMARKET_EXPANSION_LIST_PATH, merged_expansion_list)

    report: dict = {
        "generated_at": _utc_now_iso(),
        "new_ids": sorted(plan.new_ids),
        "removed_ids": sorted(plan.removed_ids),
        "orphaned_ids": sorted(plan.orphaned_ids),
        "unchanged_count": len(plan.unchanged_ids),
        "migrations": [
            {"old_id": m.old_id, "new_id": m.new_id, "reason": m.reason} for m in plan.migrations
        ],
        "scrape_ids": sorted(plan.scrape_ids),
        "cards_scraped": 0,
        "details_scraped": 0,
    }

    if not plan.scrape_ids:
        log_line("[INCREMENTAL] no new expansions to scrape")
        conflicts = validate_catalog_integrity(
            cards=existing_cards, details=existing_details, plan=plan
        )
        raise_on_conflicts(conflicts)
        validate_export_match_keys(existing_details)
        export_prices_from_details(
            catalog_path=catalog_path,
            output_path=output_prices_path,
            validate=True,
        )
        report["status"] = "no_new_expansions"
        save_json(CARDMARKET_INCREMENTAL_REPORT_PATH, report)
        return report

    log_line(
        f"[INCREMENTAL] scraping {len(plan.scrape_ids)} expansion(s): "
        f"new={len(plan.new_ids)} migrations={len(plan.migrations)}"
    )

    expansions_to_scrape = [
        e for e in merged_expansion_list if int(e["expansion_id"]) in plan.scrape_ids
    ]
    scrape_result = scrape_expansions(expansions_to_scrape, session=session)
    report["cards_scraped"] = len(scrape_result["cards"])

    merged_cards, card_conflicts = merge_card_lists(
        existing_cards,
        scrape_result["cards"],
        purge_expansion_ids=plan.purge_expansion_ids,
    )
    raise_on_conflicts(card_conflicts)

    purge_card_ids = card_ids_for_expansion_ids(existing_cards, plan.purge_expansion_ids)
    merged_details, detail_conflicts = merge_card_details(
        existing_details,
        [],
        purge_card_ids=purge_card_ids,
    )
    raise_on_conflicts(detail_conflicts)

    conflicts = validate_catalog_integrity(cards=merged_cards, details=merged_details, plan=plan)
    raise_on_conflicts(conflicts)

    from ygo_app.cardmarket.card_list_scrape import _save_card_list_artifacts
    from ygo_app.cardmarket.paths import (
        CARDMARKET_EMPTY_EXPANSIONS_PATH,
        CARDMARKET_REJECTED_EXPANSIONS_PATH,
    )

    empty_expansions = (
        load_json_list(CARDMARKET_EMPTY_EXPANSIONS_PATH)
        if CARDMARKET_EMPTY_EXPANSIONS_PATH.is_file()
        else []
    )
    empty_expansions.extend(scrape_result["empty_expansions"])

    _save_card_list_artifacts(
        all_cards=merged_cards,
        expansions=merged_expansion_list,
        empty_expansions=empty_expansions,
        rejected_expansions=scrape_result["rejected_expansions"],
        card_list_path=CARDMARKET_CARD_LIST_PATH,
        expansion_list_path=CARDMARKET_EXPANSION_LIST_PATH,
        empty_path=CARDMARKET_EMPTY_EXPANSIONS_PATH,
        rejected_path=CARDMARKET_REJECTED_EXPANSIONS_PATH,
    )

    if update_seed:
        regenerate_expansion_seed(CARDMARKET_EXPANSION_LIST_PATH)

    save_json(CARDMARKET_CARD_DETAILS_PATH, merged_details)

    details_before = len(merged_details)
    run_card_details_scrape(
        session=session,
        expansion_ids=plan.scrape_ids,
        skip_existing=True,
        merge_output=True,
        purge_card_ids=purge_card_ids,
    )
    merged_details = load_json_list(CARDMARKET_CARD_DETAILS_PATH)
    report["details_scraped"] = len(merged_details) - details_before
    conflicts = validate_catalog_integrity(cards=merged_cards, details=merged_details, plan=plan)
    raise_on_conflicts(conflicts)
    validate_export_match_keys(merged_details)

    export_stats = export_prices_from_details(
        catalog_path=catalog_path,
        output_path=output_prices_path,
        validate=True,
    )
    report["export"] = export_stats
    report["status"] = "ok"
    save_json(CARDMARKET_INCREMENTAL_REPORT_PATH, report)
    log_line(f"[INCREMENTAL] complete — report at {CARDMARKET_INCREMENTAL_REPORT_PATH}")
    return report


def _run(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(
        description="Incremental Cardmarket scrape (new expansions and ID migrations only)"
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG_PATH,
        help="Yugipedia catalog JSON for export",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=CARDMARKET_PRICES_PATH,
        help="Output cardmarket_prices.json",
    )
    parser.add_argument(
        "--no-update-seed",
        action="store_true",
        help="Skip regenerating expansion_seed.json",
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
            run_incremental_scrape(
                session=session,
                catalog_path=args.catalog,
                output_prices_path=args.output,
                update_seed=not args.no_update_seed,
            )
        return 0
    except IncrementalConflictError as exc:
        log_line(f"[INCREMENTAL] conflict: {exc}")
        return 1
    except FileNotFoundError as exc:
        log_line(f"[INCREMENTAL] error: {exc}")
        return 1


def main(argv: list[str] | None = None) -> int:
    return run_job_logged(Path(__file__).stem, lambda: _run(argv))


if __name__ == "__main__":
    sys.exit(main())
