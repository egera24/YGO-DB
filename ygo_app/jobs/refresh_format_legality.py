"""Refresh per-format card legality flags (Speed Duel, Edison)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select

from ygo_app.database import SessionLocal
from ygo_app.formats.registry import EDISON_POOL_CUTOFF, GOAT_POOL_CUTOFF
from ygo_app.formats.pool import expansion_abbr_from_set_code
from ygo_app.job_logging import job_log_session
from ygo_app.models import CardFormatLegality, Printing, TcgSet
from ygo_app.yugipedia.scrape_progress import log_line

SPEED_DUEL_FORMAT = "speed_duel"
EDISON_FORMAT = "edison"
GOAT_FORMAT = "goat"


def _legal_ids_by_cutoff(session, cutoff: date) -> set[int]:
    printing_rows = session.execute(select(Printing.card_id, Printing.set_code)).all()
    legal_ids: set[int] = set()
    for card_id, set_code in printing_rows:
        abbr = expansion_abbr_from_set_code(set_code or "")
        if not abbr:
            continue
        tcg_set = session.get(TcgSet, abbr)
        if tcg_set and tcg_set.release_date and tcg_set.release_date <= cutoff:
            legal_ids.add(int(card_id))
    return legal_ids


def _write_legality_flags(session, format_code: str, legal_ids: set[int]) -> int:
    session.execute(
        delete(CardFormatLegality).where(CardFormatLegality.format_code == format_code)
    )
    for card_id in legal_ids:
        session.add(
            CardFormatLegality(card_id=card_id, format_code=format_code, is_legal=True)
        )
    session.commit()
    return len(legal_ids)


def refresh_speed_duel_legality(session) -> int:
    rows = session.execute(
        select(Printing.card_id).where(Printing.set_name.ilike("%Speed Duel%")).distinct()
    ).all()
    legal_ids = {int(row[0]) for row in rows}
    return _write_legality_flags(session, SPEED_DUEL_FORMAT, legal_ids)


def refresh_edison_legality(session, cutoff: date = EDISON_POOL_CUTOFF) -> int:
    return _write_legality_flags(session, EDISON_FORMAT, _legal_ids_by_cutoff(session, cutoff))


def refresh_goat_legality(session, cutoff: date = GOAT_POOL_CUTOFF) -> int:
    return _write_legality_flags(session, GOAT_FORMAT, _legal_ids_by_cutoff(session, cutoff))


def refresh_format_legality() -> dict:
    session = SessionLocal()
    try:
        speed_count = refresh_speed_duel_legality(session)
        edison_count = refresh_edison_legality(session)
        goat_count = refresh_goat_legality(session)
        log_line(f"[LEGality] speed_duel legal cards: {speed_count}")
        log_line(f"[LEGality] edison legal cards: {edison_count}")
        log_line(f"[LEGality] goat legal cards: {goat_count}")
        return {
            "speed_duel_legal": speed_count,
            "edison_legal": edison_count,
            "goat_legal": goat_count,
        }
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh format legality flags")
    parser.parse_args()

    with job_log_session("refresh_format_legality") as log:
        try:
            summary = refresh_format_legality()
            out_path = Path("data/catalog/format_legality_summary.json")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            log.exit_code = 0
        except Exception as exc:
            log_line(f"[LEGality] ERROR: {exc}")
            log.exit_code = 1
            raise
    return log.exit_code


if __name__ == "__main__":
    sys.exit(main())
