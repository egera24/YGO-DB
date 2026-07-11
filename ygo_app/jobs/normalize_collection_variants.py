"""Normalize collection condition/edition aliases and merge duplicate variant rows."""

from __future__ import annotations

import argparse
import sys

from ygo_app.collection_variant_backfill import (
    dry_run_collection_variants,
    normalize_collection_variants_in_db,
)
from ygo_app.database import SessionLocal, init_db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Canonicalize condition/edition aliases on collection_items and "
            "merge rows that collapse to the same variant identity."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report counts without committing changes.",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="Limit backfill to a single user id.",
    )
    args = parser.parse_args(argv)

    init_db()
    session = SessionLocal()
    try:
        if args.dry_run:
            stats = dry_run_collection_variants(session, user_id=args.user_id)
            print(
                "Dry run: "
                f"{stats['rows_updated']} row(s) would be updated, "
                f"{stats['rows_merged']} merge(s) across "
                f"{stats['groups_processed']} identity group(s) "
                f"({stats['rows_deleted']} row(s) would be removed)."
            )
            return 0

        stats = normalize_collection_variants_in_db(
            session,
            user_id=args.user_id,
            dry_run=False,
        )
        print(
            "Normalized collection variants: "
            f"{stats['rows_updated']} row(s) updated, "
            f"{stats['rows_merged']} merge(s), "
            f"{stats['rows_deleted']} duplicate row(s) removed."
        )
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
