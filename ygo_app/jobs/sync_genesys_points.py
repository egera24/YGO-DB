"""CLI job: sync Genesys point lists from Yugipedia."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ygo_app.database import SessionLocal
from ygo_app.genesys.fetch import START_URL, crawl_point_lists
from ygo_app.genesys.import_data import upsert_point_list
from ygo_app.genesys.parse import parse_point_list_file
from ygo_app.banlist.match import build_card_name_index
from ygo_app.job_logging import job_log_session
from ygo_app.yugipedia.scrape_progress import log_line


def sync_genesys_points(*, fixture: Path | None = None) -> dict:
    if fixture:
        lists = [
            parse_point_list_file(
                fixture,
                source_url="https://yugipedia.com/wiki/September_22,_2025_Point_List",
            )
        ]
    else:
        lists = crawl_point_lists(START_URL)

    session = SessionLocal()
    card_index = build_card_name_index(session)
    summary = {
        "lists_processed": 0,
        "entries_matched": 0,
        "entries_unmatched": 0,
        "lists": [],
    }
    try:
        for list_data in lists:
            point_list, matched, unmatched = upsert_point_list(
                session, list_data, card_index=card_index
            )
            summary["lists_processed"] += 1
            summary["entries_matched"] += matched
            summary["entries_unmatched"] += unmatched
            summary["lists"].append(
                {
                    "id": point_list.id,
                    "label": point_list.label,
                    "matched": matched,
                    "unmatched": unmatched,
                }
            )
            log_line(
                f"[GENESYS] {point_list.label}: {matched} matched, {unmatched} unmatched"
            )
    finally:
        session.close()

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Genesys point lists")
    parser.add_argument(
        "--fixture",
        type=Path,
        help="Parse a local HTML fixture instead of live Yugipedia fetch",
    )
    args = parser.parse_args()

    with job_log_session("sync_genesys_points") as log:
        try:
            summary = sync_genesys_points(fixture=args.fixture)
            out_path = Path("data/catalog/genesys_sync_summary.json")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            log_line(f"[GENESYS] summary written to {out_path}")
            log.exit_code = 0
        except Exception as exc:
            log_line(f"[GENESYS] ERROR: {exc}")
            log.exit_code = 1
            raise
    return log.exit_code


if __name__ == "__main__":
    sys.exit(main())
