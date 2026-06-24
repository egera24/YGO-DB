"""Local repairs for Cardmarket job-2 catalog artifacts (no Cardmarket requests)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ygo_app.cardmarket.artifact_io import load_json_list, save_json
from ygo_app.cardmarket.catalog_consistency import (
    audit_card_list_coverage,
    gap_expansion_ids,
    purge_orphan_card_rows,
)
from ygo_app.cardmarket.paths import (
    CARDMARKET_CARD_LIST_PATH,
    CARDMARKET_EMPTY_EXPANSIONS_PATH,
    CARDMARKET_EXPANSION_LIST_PATH,
    CARDMARKET_REJECTED_EXPANSIONS_PATH,
)
from ygo_app.job_logging import run_job_logged
from ygo_app.yugipedia.scrape_progress import log_line


def _load(path: Path) -> list:
    if not path.is_file():
        return []
    return load_json_list(path)


def _run(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(
        description="Repair local Cardmarket job-2 artifacts without re-scraping accounted expansions"
    )
    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=None,
        help="Override data/catalog directory (default: project data/catalog)",
    )
    parser.add_argument(
        "--purge-orphans",
        action="store_true",
        help="Remove card rows for expansion_ids not in cardmarket_expansion_list.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report planned repairs without writing files",
    )
    args = parser.parse_args(argv)

    if args.catalog_dir is not None:
        catalog = args.catalog_dir
        paths = {
            "expansion_list": catalog / "cardmarket_expansion_list.json",
            "card_list": catalog / "cardmarket_card_list.json",
            "empty": catalog / "cardmarket_empty_expansions.json",
            "rejected": catalog / "cardmarket_rejected_expansions.json",
        }
    else:
        paths = {
            "expansion_list": CARDMARKET_EXPANSION_LIST_PATH,
            "card_list": CARDMARKET_CARD_LIST_PATH,
            "empty": CARDMARKET_EMPTY_EXPANSIONS_PATH,
            "rejected": CARDMARKET_REJECTED_EXPANSIONS_PATH,
        }

    if not paths["expansion_list"].is_file():
        log_line("[REPAIR] cardmarket_expansion_list.json: MISSING")
        return 1
    if not paths["card_list"].is_file():
        log_line("[REPAIR] cardmarket_card_list.json: MISSING")
        return 1

    expansion_list = _load(paths["expansion_list"])
    card_list = _load(paths["card_list"])
    empty_expansions = _load(paths["empty"])
    rejected_expansions = _load(paths["rejected"])

    before = audit_card_list_coverage(
        expansion_list=expansion_list,
        card_list=card_list,
        empty_expansions=empty_expansions,
        rejected_expansions=rejected_expansions,
    )
    gaps = gap_expansion_ids(before)
    log_line(
        f"[REPAIR] coverage: ok={before.ok} gaps={len(gaps)} "
        f"orphan_expansions={len(before.orphan_card_expansion_ids)}"
    )

    if not args.purge_orphans:
        if before.orphan_card_expansion_ids:
            log_line(
                "[REPAIR] run with --purge-orphans to remove "
                f"{len(before.orphan_card_expansion_ids)} non-TCG expansion(s) from the card list"
            )
        if gaps:
            log_line(
                f"[REPAIR] scrape gaps only: python -m ygo_app.jobs.scrape_cardmarket_card_list "
                f"--browser --headed --polite --only-gaps"
            )
        return 0 if before.ok else 1

    cleaned_cards, removed_ids = purge_orphan_card_rows(card_list, expansion_list)
    if not removed_ids:
        log_line("[REPAIR] no orphan card rows to purge")
        return 0 if before.ok else 1

    removed_rows = len(card_list) - len(cleaned_cards)
    log_line(
        f"[REPAIR] would remove {removed_rows} card row(s) "
        f"from {len(removed_ids)} orphan expansion(s): {removed_ids}"
    )

    if args.dry_run:
        return 0

    save_json(paths["card_list"], cleaned_cards)
    after = audit_card_list_coverage(
        expansion_list=expansion_list,
        card_list=cleaned_cards,
        empty_expansions=empty_expansions,
        rejected_expansions=rejected_expansions,
    )
    log_line(f"[REPAIR] saved card list; coverage ok={after.ok}")
    if gap_expansion_ids(after):
        log_line(
            "[REPAIR] remaining gaps — run: "
            "python -m ygo_app.jobs.scrape_cardmarket_card_list --browser --headed --polite --only-gaps"
        )
    return 0 if after.ok else 1


def main(argv: list[str] | None = None) -> int:
    return run_job_logged(Path(__file__).stem, lambda: _run(argv))


if __name__ == "__main__":
    sys.exit(main())
