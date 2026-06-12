"""Import YGOProDeck catalog and DragonShield CSV into the database."""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session
from tqdm import tqdm

from ygo_app.catalog import fetch_card_entries, load_card_entries
from ygo_app.config import DB_PATH, DEFAULT_CARDS_JSON, DEFAULT_COLLECTION_CSV
from ygo_app.database import Base, SessionLocal, engine, is_postgres, is_sqlite
from ygo_app.models import Card, CollectionItem, Printing
from ygo_app.import_progress import ProgressThrottle
from ygo_app.utils import normalize_rarity_code, rarity_display

IMPORT_ERROR_COLUMN = "Import Error"


def _detach_collection_printing_links(session: Session) -> int:
    """Clear printing_id so catalog rows can be replaced without FK violations."""
    result = session.execute(
        update(CollectionItem)
        .where(CollectionItem.printing_id.isnot(None))
        .values(printing_id=None)
    )
    return result.rowcount or 0


def _relink_collection_printing_links(session: Session) -> int:
    """Re-attach collection_items to new printings by set_code + rarity_code."""
    if is_postgres():
        result = session.execute(
            text(
                """
                UPDATE collection_items AS ci
                SET printing_id = p.id
                FROM printings AS p
                WHERE p.set_code = ci.set_code
                  AND p.set_rarity_code = ci.rarity_code
                  AND ci.printing_id IS NULL
                """
            )
        )
    else:
        result = session.execute(
            text(
                """
                UPDATE collection_items
                SET printing_id = (
                    SELECT p.id FROM printings AS p
                    WHERE p.set_code = collection_items.set_code
                      AND p.set_rarity_code = collection_items.rarity_code
                    LIMIT 1
                )
                WHERE printing_id IS NULL
                  AND EXISTS (
                    SELECT 1 FROM printings AS p
                    WHERE p.set_code = collection_items.set_code
                      AND p.set_rarity_code = collection_items.rarity_code
                  )
                """
            )
        )
    return result.rowcount or 0


def reset_db():
    if is_sqlite() and engine.url.database:
        db_file = Path(engine.url.database)
        if db_file.exists():
            db_file.unlink()
    else:
        Base.metadata.drop_all(bind=engine)
    init_db()


def init_db():
    # SQLite local dev: create tables without Alembic. Postgres/cloud: migrations only.
    if is_sqlite():
        Base.metadata.create_all(bind=engine)


def _card_from_api(entry: dict) -> Card:
    images = entry.get("card_images") or [{}]
    img = images[0] if images else {}
    link_rating = _int_or_none(entry.get("link_rating"))
    pendulum_scale = _int_or_none(entry.get("pendulum_scale"))
    return Card(
        id=int(entry["id"]),
        name=entry.get("name", ""),
        type=entry.get("type"),
        human_readable_type=entry.get("humanReadableCardType"),
        frame_type=entry.get("frameType"),
        desc=entry.get("desc"),
        atk=_int_or_none(entry.get("atk")),
        def_=_int_or_none(entry.get("def")),
        level=_int_or_none(entry.get("level")),
        race=entry.get("race"),
        attribute=entry.get("attribute"),
        archetype=entry.get("archetype"),
        linkval=_int_or_none(entry.get("linkval")) or link_rating,
        scale=_int_or_none(entry.get("scale")) or pendulum_scale,
        category=entry.get("category"),
        types=entry.get("types"),
        mechanic=entry.get("mechanic"),
        rank=_int_or_none(entry.get("rank")),
        link_rating=link_rating,
        pendulum_scale=pendulum_scale,
        link_markers=entry.get("link_markers"),
        summoning_condition=entry.get("summoning_condition"),
        ygoprodeck_url=entry.get("ygoprodeck_url"),
        image_url=img.get("image_url"),
        image_url_small=img.get("image_url_small"),
    )


def _printing_rarity_code(card_set: dict) -> str:
    code = normalize_rarity_code(card_set.get("set_rarity_code", ""))
    if code:
        return code
    label = (card_set.get("set_rarity") or "Unknown").strip()
    if label.startswith("(") and label.endswith(")"):
        return label
    return f"({label})"


def _int_or_none(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def import_cards_entries(
    entries: list[dict],
    *,
    limit: int | None = None,
    batch_size: int = 500,
) -> tuple[int, int]:
    init_db()
    session = SessionLocal()
    cards_imported = 0
    printings_imported = 0

    try:
        if limit:
            entries = entries[:limit]

        _detach_collection_printing_links(session)

        # Cards CASCADE to printings; printings must not be deleted first while
        # collection_items still reference printing_id (no ON DELETE SET NULL).
        session.query(Card).delete()
        session.commit()

        batch_cards: list[Card] = []
        batch_printings: list[Printing] = []

        for entry in tqdm(entries, desc="Importing cards"):
            if "category" not in entry and entry.get("frameType") is not None:
                from ygo_app.yugipedia.card_import import enrich_ygopro_entry

                entry = enrich_ygopro_entry(entry)
            card = _card_from_api(entry)
            batch_cards.append(card)
            seen_printings: set[tuple[str, str]] = set()

            for cs in entry.get("card_sets") or []:
                set_code = cs.get("set_code")
                if not set_code:
                    continue
                rarity_code = _printing_rarity_code(cs)
                key = (set_code, rarity_code)
                if key in seen_printings:
                    continue
                seen_printings.add(key)
                batch_printings.append(
                    Printing(
                        card_id=card.id,
                        set_name=cs.get("set_name"),
                        set_code=set_code,
                        set_rarity=cs.get("set_rarity"),
                        set_rarity_code=rarity_code,
                        set_price=cs.get("set_price"),
                    )
                )

            if len(batch_cards) >= batch_size:
                session.add_all(batch_cards)
                session.flush()
                session.add_all(batch_printings)
                session.commit()
                cards_imported += len(batch_cards)
                printings_imported += len(batch_printings)
                batch_cards.clear()
                batch_printings.clear()

        if batch_cards:
            session.add_all(batch_cards)
            session.flush()
            session.add_all(batch_printings)
            session.commit()
            cards_imported += len(batch_cards)
            printings_imported += len(batch_printings)

        _relink_collection_printing_links(session)
        session.commit()

        try:
            from ygo_app.api.routes.meta import invalidate_catalog_filters_cache

            invalidate_catalog_filters_cache()
        except Exception:
            pass

        return cards_imported, printings_imported
    finally:
        session.close()


def import_cards_json(
    path: Path,
    *,
    limit: int | None = None,
    batch_size: int = 500,
) -> tuple[int, int]:
    entries = load_card_entries(path)
    return import_cards_entries(entries, limit=limit, batch_size=batch_size)


def import_cards_from_api(*, limit: int | None = None) -> tuple[int, int]:
    entries = fetch_card_entries()
    return import_cards_entries(entries, limit=limit)


def _link_printing(session: Session, set_code: str, rarity_code: str) -> int | None:
    stmt = (
        select(Printing.id)
        .where(Printing.set_code == set_code)
        .where(Printing.set_rarity_code == rarity_code)
        .limit(1)
    )
    row = session.execute(stmt).first()
    return row[0] if row else None


def _match_printing(
    session: Session, set_code: str, rarity_code: str
) -> tuple[int | None, str | None]:
    if not set_code:
        return None, "Missing card number"
    printing_id = _link_printing(session, set_code, rarity_code)
    if printing_id is not None:
        return printing_id, None
    has_set = session.execute(
        select(Printing.id).where(Printing.set_code == set_code).limit(1)
    ).scalar()
    if has_set:
        return None, (
            f"Rarity '{rarity_display(rarity_code)}' not found for set code '{set_code}'"
        )
    return None, f"Set code '{set_code}' not found in catalog"


@dataclass
class CollectionImportResult:
    imported: int
    rejected: list[dict] = field(default_factory=list)
    fieldnames: list[str] = field(default_factory=list)


def import_collection_csv(
    path: Path | str,
    *,
    user_id: int,
    replace: bool = True,
    progress_callback: Callable[[int, int], None] | None = None,
) -> CollectionImportResult:
    path = Path(path)
    init_db()
    session = SessionLocal()
    imported = 0
    rejected: list[dict] = []
    output_fieldnames: list[str] = []

    def _process_row(row: dict) -> None:
        nonlocal imported
        set_code = (row.get("Card Number") or "").strip()
        rarity_code = normalize_rarity_code(row.get("Rarity") or "")
        printing_id, reason = _match_printing(session, set_code, rarity_code)
        if reason:
            rejected.append({**row, IMPORT_ERROR_COLUMN: reason})
            return

        from ygo_app.models import CollectionItemFolder
        from ygo_app.services import get_or_create_folder

        quantity = int(row.get("Quantity") or 1)
        folder_raw = (row.get("Folder Name") or "").strip()
        folder = None
        if folder_raw:
            try:
                folder = get_or_create_folder(session, user_id, folder_raw)
            except ValueError:
                folder = None

        item = CollectionItem(
            user_id=user_id,
            set_code=set_code,
            rarity_code=rarity_code,
            card_name=row.get("Card Name"),
            expansion_code=row.get("Set Code"),
            set_name=row.get("Set Name"),
            quantity=quantity,
            trade_quantity=int(row.get("Trade Quantity") or 0),
            condition=row.get("Condition"),
            edition=row.get("Printing") or "Unlimited",
            language=row.get("Language"),
            price_bought=_float_or_none(row.get("Price Bought")),
            date_bought=row.get("Date Bought"),
            avg_price=_float_or_none(row.get("AVG")),
            low_price=_float_or_none(row.get("LOW")),
            trend_price=_float_or_none(row.get("TREND")),
            printing_id=printing_id,
        )
        session.add(item)
        session.flush()
        session.add(
            CollectionItemFolder(
                collection_item_id=item.id,
                folder_id=folder.id if folder else None,
                quantity=quantity,
            )
        )
        imported += 1

        if imported % 500 == 0:
            session.commit()

    try:
        if replace:
            from ygo_app.models import CollectionFolder

            session.query(CollectionItem).filter(
                CollectionItem.user_id == user_id
            ).delete()
            session.query(CollectionFolder).filter(
                CollectionFolder.user_id == user_id
            ).delete()
            session.commit()

        with path.open("r", encoding="utf-8-sig", newline="") as f:
            lines = f.readlines()
        if lines and lines[0].strip() == '"sep=,"':
            lines = lines[1:]

        reader = csv.DictReader(lines)
        output_fieldnames = list(reader.fieldnames or []) + [IMPORT_ERROR_COLUMN]
        rows = list(reader)
        total = len(rows)
        if progress_callback is not None and total > 0:
            progress_callback(0, total)
        throttle = ProgressThrottle() if progress_callback else None

        def _emit_progress(current: int) -> None:
            if progress_callback is None:
                return
            if throttle is not None and not throttle.should_emit(current):
                return
            progress_callback(current, total)

        if progress_callback is not None:
            row_iter = enumerate(rows, start=1)
        else:
            row_iter = enumerate(tqdm(rows, desc="Importing collection"), start=1)

        for index, row in row_iter:
            _process_row(row)
            if progress_callback is not None:
                _emit_progress(index)

        if progress_callback is not None and total > 0:
            progress_callback(total, total)

        session.commit()
        return CollectionImportResult(
            imported=imported,
            rejected=rejected,
            fieldnames=output_fieldnames,
        )
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import card DB and collection")
    parser.add_argument("--cards", type=Path, default=DEFAULT_CARDS_JSON)
    parser.add_argument("--collection", type=Path, default=DEFAULT_COLLECTION_CSV)
    parser.add_argument("--from-api", action="store_true", help="Fetch catalog from YGOProDeck API")
    parser.add_argument("--skip-cards", action="store_true")
    parser.add_argument("--skip-collection", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="Import only N cards (testing)")
    parser.add_argument("--user-id", type=int, default=1, help="User ID for collection import")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing database / tables before import",
    )
    args = parser.parse_args(argv)

    if args.reset:
        if DB_PATH is not None and DB_PATH.exists():
            print(f"Removing {DB_PATH}")
            DB_PATH.unlink()
        else:
            reset_db()

    if not args.skip_cards:
        if args.from_api:
            c, p = import_cards_from_api(limit=args.limit)
        else:
            if not args.cards.exists():
                print(f"Cards file not found: {args.cards}", file=sys.stderr)
                print("Use --from-api to fetch from YGOProDeck instead.", file=sys.stderr)
                return 1
            c, p = import_cards_json(args.cards, limit=args.limit)
        print(f"Imported {c} cards and {p} printings.")

    if not args.skip_collection:
        if not args.collection.exists():
            print(f"Collection file not found: {args.collection}", file=sys.stderr)
            return 1
        result = import_collection_csv(args.collection, user_id=args.user_id)
        print(
            f"Imported {result.imported} collection rows for user_id={args.user_id}."
        )
        if result.rejected:
            print(
                f"Rejected {len(result.rejected)} rows (no catalog match).",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
