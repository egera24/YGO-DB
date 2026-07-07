"""CLI job: sync Konami EU banlists."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ygo_app.banlist.fetch import fetch_list, fetch_options
from ygo_app.banlist.import_data import upsert_banlist_revision
from ygo_app.banlist.match import build_card_name_index
from ygo_app.banlist.parse import normalize_list_payload
from ygo_app.database import SessionLocal
from ygo_app.job_logging import job_log_session
from ygo_app.yugipedia.scrape_progress import log_line


def sync_banlists(*, skip_existing: bool = False) -> dict:
    options = fetch_options()
    log_line(f"[BANLIST] discovered {len(options)} historical lists")

    session = SessionLocal()
    card_index = build_card_name_index(session)
    summary = {
        "lists_processed": 0,
        "lists_skipped": 0,
        "entries_matched": 0,
        "entries_unmatched": 0,
        "revisions": [],
    }

    try:
        from ygo_app.models import BanlistRevision
        from sqlalchemy import select

        existing_ids = set(
            session.execute(select(BanlistRevision.source_list_id)).scalars().all()
        )

        for list_id, label in options.items():
            if skip_existing and list_id in existing_ids:
                summary["lists_skipped"] += 1
                continue
            payload = fetch_list(list_id)
            normalized = normalize_list_payload(
                payload, source_list_id=list_id, label=label
            )
            revision, matched, unmatched = upsert_banlist_revision(
                session, normalized, card_index=card_index
            )
            summary["lists_processed"] += 1
            summary["entries_matched"] += matched
            summary["entries_unmatched"] += unmatched
            summary["revisions"].append(
                {
                    "id": revision.id,
                    "source_list_id": revision.source_list_id,
                    "label": revision.label,
                    "matched": matched,
                    "unmatched": unmatched,
                }
            )
            log_line(
                f"[BANLIST] {revision.label}: {matched} matched, {unmatched} unmatched"
            )

        if not skip_existing or "current" not in existing_ids:
            current_payload = fetch_list("current")
            current_label = current_payload.get("from") or "Current"
            normalized = normalize_list_payload(
                current_payload, source_list_id="current", label=str(current_label)
            )
            revision, matched, unmatched = upsert_banlist_revision(
                session, normalized, card_index=card_index
            )
            summary["lists_processed"] += 1
            summary["entries_matched"] += matched
            summary["entries_unmatched"] += unmatched
            summary["revisions"].append(
                {
                    "id": revision.id,
                    "source_list_id": revision.source_list_id,
                    "label": revision.label,
                    "matched": matched,
                    "unmatched": unmatched,
                }
            )
            log_line(
                f"[BANLIST] current ({revision.label}): {matched} matched, {unmatched} unmatched"
            )
        else:
            summary["lists_skipped"] += 1
    finally:
        session.close()

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Konami EU banlists")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip revisions already stored (monthly incremental mode)",
    )
    args = parser.parse_args()

    with job_log_session("sync_banlists") as log:
        try:
            summary = sync_banlists(skip_existing=args.skip_existing)
            out_path = Path("data/catalog/banlist_sync_summary.json")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            log_line(f"[BANLIST] summary written to {out_path}")
            log.exit_code = 0
        except Exception as exc:
            log_line(f"[BANLIST] ERROR: {exc}")
            log.exit_code = 1
            raise
    return log.exit_code


if __name__ == "__main__":
    sys.exit(main())
