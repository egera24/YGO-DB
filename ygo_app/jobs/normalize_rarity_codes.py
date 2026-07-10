"""Normalize printings and collection rarity codes using the rarity registry."""

from __future__ import annotations

import argparse
import sys

from ygo_app.database import SessionLocal, init_db
from ygo_app.import_data import normalize_rarity_codes_in_db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Canonicalize rarity codes in printings and collection_items."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report counts without committing changes.",
    )
    args = parser.parse_args(argv)

    init_db()
    session = SessionLocal()
    try:
        if args.dry_run:
            from sqlalchemy import select

            from ygo_app.models import CollectionItem, Printing
            from ygo_app.rarity_registry import resolve_rarity

            printing_updates = 0
            for printing in session.scalars(select(Printing)):
                resolved = resolve_rarity(printing.set_rarity_code or "")
                if resolved is None and printing.set_rarity:
                    resolved = resolve_rarity(printing.set_rarity)
                if resolved is None:
                    continue
                if printing.set_rarity_code != resolved.normalized_code:
                    printing_updates += 1

            collection_updates = 0
            for item in session.scalars(select(CollectionItem)):
                resolved = resolve_rarity(item.rarity_code)
                if resolved is None:
                    continue
                if item.rarity_code != resolved.normalized_code:
                    collection_updates += 1

            print(
                "Dry run: "
                f"{printing_updates} printing(s), "
                f"{collection_updates} collection row(s) would be updated."
            )
            return 0

        stats = normalize_rarity_codes_in_db(session)
        session.commit()
        print(
            "Normalized rarity codes: "
            f"{stats['printings_updated']} printing(s), "
            f"{stats['collection_items_updated']} collection row(s); "
            f"refreshed {stats['collection_links_refreshed']} printing link(s)."
        )
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
