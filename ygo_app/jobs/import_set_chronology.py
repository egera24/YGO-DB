"""Import Yugipedia set chronology JSON into tcg_sets."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from ygo_app.database import SessionLocal
from ygo_app.db_migrate import ensure_db_at_head
from ygo_app.models import TcgSet
from ygo_app.yugipedia.date_parse import parse_yugipedia_date
from ygo_app.yugipedia.paths import SET_CHRONOLOGY_PATH


def load_set_chronology(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array in {path}")
    return data


def import_set_chronology_rows(rows: list[dict]) -> int:
    session = SessionLocal()
    imported = 0
    try:
        for row in rows:
            abbr = (row.get("abbr") or "").strip()
            if not abbr:
                continue
            release = row.get("release_date")
            release_date = None
            if isinstance(release, str) and release:
                release_date = parse_yugipedia_date(release)
            elif isinstance(release, date):
                release_date = release

            existing = session.get(TcgSet, abbr)
            if existing:
                existing.name = row.get("name") or existing.name
                existing.set_type = row.get("set_type")
                existing.series = row.get("series")
                existing.region = row.get("region") or "TCG"
                existing.release_date = release_date
            else:
                session.add(
                    TcgSet(
                        abbr=abbr,
                        name=row.get("name") or abbr,
                        set_type=row.get("set_type"),
                        series=row.get("series"),
                        region=row.get("region") or "TCG",
                        release_date=release_date,
                    )
                )
            imported += 1
        session.commit()
    finally:
        session.close()
    return imported


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import Yugipedia set chronology JSON")
    parser.add_argument(
        "--json",
        type=Path,
        default=SET_CHRONOLOGY_PATH,
        help="Path to yugipedia_set_chronology.json",
    )
    args = parser.parse_args(argv)

    if not args.json.exists():
        print(f"Set chronology file not found: {args.json}", file=sys.stderr)
        return 1

    ensure_db_at_head()
    rows = load_set_chronology(args.json)
    count = import_set_chronology_rows(rows)
    print(f"Imported {count} tcg_sets rows from {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
