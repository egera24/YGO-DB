"""Import YGOProDeck catalog and DragonShield CSV into the database."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session
from tqdm import tqdm

from ygo_app.catalog import fetch_card_entries, load_card_entries
from ygo_app.config import DB_PATH, DEFAULT_CARDS_JSON, DEFAULT_COLLECTION_CSV
from ygo_app.database import Base, SessionLocal, engine, is_sqlite
from ygo_app.models import Card, CollectionItem, Printing
from ygo_app.search_index import ensure_search_index, rebuild_search_index
from ygo_app.utils import normalize_rarity_code


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
    with engine.connect() as conn:
        ensure_search_index(conn)


def _card_from_api(entry: dict) -> Card:
    images = entry.get("card_images") or [{}]
    img = images[0] if images else {}
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
        linkval=_int_or_none(entry.get("linkval")),
        scale=_int_or_none(entry.get("scale")),
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

        session.query(Printing).delete()
        session.query(Card).delete()
        session.commit()

        batch_cards: list[Card] = []
        batch_printings: list[Printing] = []

        for entry in tqdm(entries, desc="Importing cards"):
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

        rebuild_search_index(session)
        session.commit()
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


def import_collection_csv(
    path: Path, *, user_id: int, replace: bool = True
) -> int:
    init_db()
    session = SessionLocal()
    imported = 0

    try:
        if replace:
            session.query(CollectionItem).filter(
                CollectionItem.user_id == user_id
            ).delete()
            session.commit()

        with path.open("r", encoding="utf-8-sig", newline="") as f:
            lines = f.readlines()
        if lines and lines[0].strip() == '"sep=,"':
            lines = lines[1:]

        reader = csv.DictReader(lines)
        rows = list(reader)

        for row in tqdm(rows, desc="Importing collection"):
            set_code = (row.get("Card Number") or "").strip()
            if not set_code:
                continue
            rarity_code = normalize_rarity_code(row.get("Rarity") or "")

            item = CollectionItem(
                user_id=user_id,
                set_code=set_code,
                rarity_code=rarity_code,
                card_name=row.get("Card Name"),
                expansion_code=row.get("Set Code"),
                set_name=row.get("Set Name"),
                quantity=int(row.get("Quantity") or 1),
                trade_quantity=int(row.get("Trade Quantity") or 0),
                condition=row.get("Condition"),
                edition=row.get("Printing") or "Unlimited",
                language=row.get("Language"),
                folder_name=row.get("Folder Name"),
                price_bought=_float_or_none(row.get("Price Bought")),
                date_bought=row.get("Date Bought"),
                avg_price=_float_or_none(row.get("AVG")),
                low_price=_float_or_none(row.get("LOW")),
                trend_price=_float_or_none(row.get("TREND")),
                printing_id=_link_printing(session, set_code, rarity_code),
            )
            session.add(item)
            imported += 1

            if imported % 500 == 0:
                session.commit()

        session.commit()
        return imported
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
        n = import_collection_csv(args.collection, user_id=args.user_id)
        print(f"Imported {n} collection rows for user_id={args.user_id}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
