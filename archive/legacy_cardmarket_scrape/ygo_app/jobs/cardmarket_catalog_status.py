"""Print human-readable status for local Cardmarket catalog scrape artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ygo_app.cardmarket.artifact_io import load_checkpoint, load_json_list
from ygo_app.cardmarket.catalog_consistency import audit_card_list_coverage
from ygo_app.cardmarket.checkpoints import format_catalog_status_report
from ygo_app.cardmarket.paths import (
    CARDMARKET_CARD_DETAILS_PATH,
    CARDMARKET_CARD_DETAILS_REJECTION_PATH,
    CARDMARKET_EMPTY_EXPANSIONS_PATH,
    CARDMARKET_EXPANSION_LIST_PATH,
    CARDMARKET_REJECTED_EXPANSIONS_PATH,
    CARDMARKET_SCRAPE_STATE_PATH,
    CARDMARKET_CARD_LIST_PATH,
)
from ygo_app.cardmarket.scrape_state import (
    find_latest_card_list,
    find_latest_expansion_list,
    load_scrape_state,
    resolve_card_list_file,
    resolve_expansion_list_file,
)
from ygo_app.job_logging import run_job_logged


def _load_list_optional(path: Path) -> list | None:
    if not path.is_file():
        return None
    return load_json_list(path)


def _run(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(
        description="Show Cardmarket catalog scrape progress from local JSON artifacts"
    )
    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=None,
        help="Override data/catalog directory (default: project data/catalog)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 when job-2 full expansion coverage audit fails",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print job-2 coverage audit as JSON instead of the text report",
    )
    args = parser.parse_args(argv)

    if args.catalog_dir is not None:
        catalog = args.catalog_dir
        paths = {
            "expansion_list": catalog / "cardmarket_expansion_list.json",
            "card_list": catalog / "cardmarket_card_list.json",
            "empty": catalog / "cardmarket_empty_expansions.json",
            "rejected": catalog / "cardmarket_rejected_expansions.json",
            "card_list_cp": catalog / "cardmarket_card_list_checkpoint.json",
            "recovery_cp": catalog / "cardmarket_card_list_recovery_checkpoint.json",
            "details": catalog / "cardmarket_card_details.json",
            "details_rejections": catalog / "cardmarket_card_details_rejection.json",
            "details_cp": catalog / "cardmarket_card_details_checkpoint.json",
        }
    else:
        state = load_scrape_state() if CARDMARKET_SCRAPE_STATE_PATH.is_file() else {}
        exp_path = resolve_expansion_list_file(state) if state else CARDMARKET_EXPANSION_LIST_PATH
        if not exp_path.is_file():
            latest = find_latest_expansion_list()
            exp_path = latest[1] if latest else CARDMARKET_EXPANSION_LIST_PATH
        card_path = resolve_card_list_file(state) if state else CARDMARKET_CARD_LIST_PATH
        if not card_path.is_file():
            latest = find_latest_card_list()
            card_path = latest[1] if latest else CARDMARKET_CARD_LIST_PATH
        paths = {
            "expansion_list": exp_path,
            "card_list": card_path,
            "empty": CARDMARKET_EMPTY_EXPANSIONS_PATH,
            "rejected": CARDMARKET_REJECTED_EXPANSIONS_PATH,
            "scrape_state": CARDMARKET_SCRAPE_STATE_PATH,
            "details": CARDMARKET_CARD_DETAILS_PATH,
            "details_rejections": CARDMARKET_CARD_DETAILS_REJECTION_PATH,
        }

    expansion_list = _load_list_optional(paths["expansion_list"])
    card_list = _load_list_optional(paths["card_list"])
    empty_expansions = _load_list_optional(paths["empty"])
    rejected_expansions = _load_list_optional(paths["rejected"])

    card_list_cp = None
    recovery_cp = None
    details_cp = None
    scrape_state = load_checkpoint(paths["scrape_state"]) if paths.get("scrape_state", Path()).is_file() else None

    coverage_ok = True
    coverage_report = None
    if expansion_list is not None and card_list is not None:
        coverage_report = audit_card_list_coverage(
            expansion_list=expansion_list,
            card_list=card_list,
            empty_expansions=empty_expansions or [],
            rejected_expansions=rejected_expansions or [],
        )
        coverage_ok = coverage_report.ok
    elif args.strict:
        coverage_ok = False

    if args.json:
        payload = coverage_report.to_dict() if coverage_report is not None else {"ok": False}
        print(json.dumps(payload, indent=2))
    else:
        report = format_catalog_status_report(
            expansion_list=expansion_list,
            card_list=card_list,
            empty_expansions=empty_expansions,
            rejected_expansions=rejected_expansions,
            card_list_checkpoint=card_list_cp or None,
            recovery_checkpoint=recovery_cp or None,
            card_details=_load_list_optional(paths["details"]),
            card_details_rejections=_load_list_optional(paths["details_rejections"]),
            card_details_checkpoint=details_cp or None,
        )
        if scrape_state:
            print("--- Scrape state (cardmarket_scrape_state.json) ---")
            print(f"  run_date: {scrape_state.get('run_date')}")
            print(f"  phase: {scrape_state.get('phase')}")
            print(f"  mode: {scrape_state.get('mode')}")
            print(f"  last_completed_seq: {scrape_state.get('last_completed_seq')}")
            print(f"  last_completed_card_index: {scrape_state.get('last_completed_card_index')}")
            print()
        print(report)

    if args.strict and not coverage_ok:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_job_logged(Path(__file__).stem, lambda: _run(argv))


if __name__ == "__main__":
    sys.exit(main())
