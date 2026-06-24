"""Print human-readable status for local Cardmarket catalog scrape artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ygo_app.cardmarket.artifact_io import load_checkpoint, load_json_list
from ygo_app.cardmarket.checkpoints import format_catalog_status_report
from ygo_app.cardmarket.paths import (
    CARDMARKET_CARD_DETAILS_CHECKPOINT_PATH,
    CARDMARKET_CARD_DETAILS_PATH,
    CARDMARKET_CARD_DETAILS_REJECTION_PATH,
    CARDMARKET_CARD_LIST_CHECKPOINT_PATH,
    CARDMARKET_CARD_LIST_PATH,
    CARDMARKET_CARD_LIST_RECOVERY_CHECKPOINT_PATH,
    CARDMARKET_EMPTY_EXPANSIONS_PATH,
    CARDMARKET_EXPANSION_LIST_PATH,
    CARDMARKET_REJECTED_EXPANSIONS_PATH,
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
        paths = {
            "expansion_list": CARDMARKET_EXPANSION_LIST_PATH,
            "card_list": CARDMARKET_CARD_LIST_PATH,
            "empty": CARDMARKET_EMPTY_EXPANSIONS_PATH,
            "rejected": CARDMARKET_REJECTED_EXPANSIONS_PATH,
            "card_list_cp": CARDMARKET_CARD_LIST_CHECKPOINT_PATH,
            "recovery_cp": CARDMARKET_CARD_LIST_RECOVERY_CHECKPOINT_PATH,
            "details": CARDMARKET_CARD_DETAILS_PATH,
            "details_rejections": CARDMARKET_CARD_DETAILS_REJECTION_PATH,
            "details_cp": CARDMARKET_CARD_DETAILS_CHECKPOINT_PATH,
        }

    card_list_cp = load_checkpoint(paths["card_list_cp"]) if paths["card_list_cp"].is_file() else None
    recovery_cp = load_checkpoint(paths["recovery_cp"]) if paths["recovery_cp"].is_file() else None
    details_cp = load_checkpoint(paths["details_cp"]) if paths["details_cp"].is_file() else None

    report = format_catalog_status_report(
        expansion_list=_load_list_optional(paths["expansion_list"]),
        card_list=_load_list_optional(paths["card_list"]),
        empty_expansions=_load_list_optional(paths["empty"]),
        rejected_expansions=_load_list_optional(paths["rejected"]),
        card_list_checkpoint=card_list_cp or None,
        recovery_checkpoint=recovery_cp or None,
        card_details=_load_list_optional(paths["details"]),
        card_details_rejections=_load_list_optional(paths["details_rejections"]),
        card_details_checkpoint=details_cp or None,
    )
    print(report)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_job_logged(Path(__file__).stem, lambda: _run(argv))


if __name__ == "__main__":
    sys.exit(main())
