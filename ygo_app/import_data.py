"""Import YGOProDeck catalog and DragonShield CSV into the database."""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from datetime import date

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session, joinedload
from tqdm import tqdm

from ygo_app.catalog import fetch_card_entries, load_card_entries
from ygo_app.config import DB_PATH, DEFAULT_CARDS_JSON, DEFAULT_COLLECTION_CSV
from ygo_app.database import Base, SessionLocal, engine, is_postgres, is_sqlite
from ygo_app.models import Card, CardErrataVersion, CollectionItem, Printing, TcgSet
from ygo_app.yugipedia.date_parse import parse_yugipedia_date
from ygo_app.yugipedia.errata import ERRATA_UI_LANGUAGE
from ygo_app.yugipedia.set_chronology import set_abbr_from_code
from ygo_app.import_progress import ProgressThrottle
from ygo_app.utils import normalize_rarity_code, rarity_display
from ygo_app.rarity_registry import (
    rarity_label_for_error,
    rarity_match_variants,
    resolve_rarity,
    variants_for_printing,
)

IMPORT_ERROR_COLUMN = "Import Error"


def _legacy_passcode_id(card_id: int | None) -> int | None:
    """Pre-migration rows used cards.id as the Konami passcode."""
    # Konami passcodes are 7–8 digits; surrogate autoincrement ids are 100M+.
    if card_id is None or card_id <= 0 or card_id > 99_999_999:
        return None
    return card_id


def _load_card_key_maps(
    session: Session,
) -> tuple[dict[int, int], dict[int, int], dict[str, int]]:
    """Build passcode/legacy-id/source_url lookup maps for upsert matching."""
    by_passcode_col: dict[int, int] = {}
    by_legacy_id: dict[int, int] = {}
    by_source_url: dict[str, int] = {}
    for cid, passcode, source_url in session.execute(
        select(Card.id, Card.passcode, Card.source_url)
    ).all():
        if passcode is not None:
            by_passcode_col[passcode] = cid
        elif legacy := _legacy_passcode_id(cid):
            by_legacy_id[legacy] = cid
        if source_url:
            by_source_url[source_url] = cid
    return by_passcode_col, by_legacy_id, by_source_url


def _resolve_existing_id(
    *,
    key: tuple[str, object],
    fields: dict,
    by_passcode_col: dict[int, int],
    by_legacy_id: dict[int, int],
    by_source_url: dict[str, int],
) -> int | None:
    """Match an import row to an existing card, preferring legacy id==passcode rows."""
    if key[0] == "p":
        passcode = int(key[1])
        if passcode in by_legacy_id:
            return by_legacy_id[passcode]
        if passcode in by_passcode_col:
            return by_passcode_col[passcode]
        source_url = fields.get("source_url")
        if source_url and source_url in by_source_url:
            return by_source_url[source_url]
        return None
    source_url = str(key[1])
    return by_source_url.get(source_url)


def _duplicate_pair_subquery() -> str:
    """SQL subquery: surrogate_id, legacy_id for legacy id==passcode duplicates."""
    return """
        SELECT c.id AS surrogate_id, c.passcode AS legacy_id
        FROM cards c
        INNER JOIN cards legacy ON legacy.id = c.passcode
        WHERE c.passcode IS NOT NULL
          AND c.id <> c.passcode
          AND legacy.passcode IS NULL
    """


def _prune_surrogate_passcode_duplicates(session: Session) -> int:
    """Drop surrogate rows when a legacy id==passcode row exists for the same card."""
    pairs_sql = _duplicate_pair_subquery()
    removed = session.execute(
        text(f"SELECT COUNT(*) FROM ({pairs_sql}) AS pairs")
    ).scalar_one()
    if not removed:
        return 0

    print(f"Pruning {removed} surrogate duplicate card rows...", flush=True)

    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        repoint_steps = [
            f"""
            UPDATE printings AS p
            SET card_id = pairs.legacy_id
            FROM ({pairs_sql}) AS pairs
            WHERE p.card_id = pairs.surrogate_id
            """,
            f"""
            UPDATE card_errata_versions AS e
            SET card_id = pairs.legacy_id
            FROM ({pairs_sql}) AS pairs
            WHERE e.card_id = pairs.surrogate_id
            """,
            f"""
            DELETE FROM user_favorites AS uf
            USING ({pairs_sql}) AS pairs,
                  user_favorites AS uf_leg
            WHERE uf.card_id = pairs.surrogate_id
              AND uf_leg.user_id = uf.user_id
              AND uf_leg.card_id = pairs.legacy_id
            """,
            f"""
            UPDATE user_favorites AS uf
            SET card_id = pairs.legacy_id
            FROM ({pairs_sql}) AS pairs
            WHERE uf.card_id = pairs.surrogate_id
            """,
            f"""
            DELETE FROM user_card_tags AS t
            USING ({pairs_sql}) AS pairs,
                  user_card_tags AS t_leg
            WHERE t.card_id = pairs.surrogate_id
              AND t_leg.user_id = t.user_id
              AND t_leg.card_id = pairs.legacy_id
              AND t_leg.tag = t.tag
            """,
            f"""
            UPDATE user_card_tags AS t
            SET card_id = pairs.legacy_id
            FROM ({pairs_sql}) AS pairs
            WHERE t.card_id = pairs.surrogate_id
            """,
            f"""
            UPDATE deck_cards AS dc
            SET card_id = pairs.legacy_id
            FROM ({pairs_sql}) AS pairs
            WHERE dc.card_id = pairs.surrogate_id
            """,
            f"""
            UPDATE banlist_entries AS be
            SET card_id = pairs.legacy_id
            FROM ({pairs_sql}) AS pairs
            WHERE be.card_id = pairs.surrogate_id
            """,
            f"""
            UPDATE genesys_point_entries AS gpe
            SET card_id = pairs.legacy_id
            FROM ({pairs_sql}) AS pairs
            WHERE gpe.card_id = pairs.surrogate_id
            """,
            f"""
            DELETE FROM card_format_legality AS cfl
            USING ({pairs_sql}) AS pairs,
                  card_format_legality AS cfl_leg
            WHERE cfl.card_id = pairs.surrogate_id
              AND cfl_leg.card_id = pairs.legacy_id
              AND cfl_leg.format_code = cfl.format_code
            """,
            f"""
            UPDATE card_format_legality AS cfl
            SET card_id = pairs.legacy_id
            FROM ({pairs_sql}) AS pairs
            WHERE cfl.card_id = pairs.surrogate_id
            """,
            f"""
            UPDATE decks AS d
            SET preview_card_id = pairs.legacy_id
            FROM ({pairs_sql}) AS pairs
            WHERE d.preview_card_id = pairs.surrogate_id
            """,
            f"""
            DELETE FROM cards AS c
            USING ({pairs_sql}) AS pairs
            WHERE c.id = pairs.surrogate_id
            """,
        ]
        for stmt in repoint_steps:
            session.execute(text(stmt))
    else:
        _prune_surrogate_passcode_duplicates_sqlite(session, pairs_sql)

    session.commit()
    print(f"Pruned {removed} surrogate duplicate card rows.", flush=True)
    return removed


def _prune_surrogate_passcode_duplicates_sqlite(session: Session, pairs_sql: str) -> None:
    """SQLite lacks UPDATE ... FROM; use per-pair statements (test DBs are small)."""
    rows = session.execute(text(f"SELECT surrogate_id, legacy_id FROM ({pairs_sql})")).all()
    for surrogate_id, legacy_id in rows:
        session.execute(
            text("UPDATE printings SET card_id = :legacy_id WHERE card_id = :surrogate_id"),
            {"legacy_id": legacy_id, "surrogate_id": surrogate_id},
        )
        session.execute(
            text(
                "UPDATE card_errata_versions SET card_id = :legacy_id WHERE card_id = :surrogate_id"
            ),
            {"legacy_id": legacy_id, "surrogate_id": surrogate_id},
        )
        session.execute(
            text(
                """
                DELETE FROM user_favorites
                WHERE card_id = :surrogate_id
                  AND user_id IN (
                    SELECT user_id FROM user_favorites WHERE card_id = :legacy_id
                  )
                """
            ),
            {"legacy_id": legacy_id, "surrogate_id": surrogate_id},
        )
        session.execute(
            text("UPDATE user_favorites SET card_id = :legacy_id WHERE card_id = :surrogate_id"),
            {"legacy_id": legacy_id, "surrogate_id": surrogate_id},
        )
        session.execute(
            text(
                """
                DELETE FROM user_card_tags
                WHERE card_id = :surrogate_id
                  AND EXISTS (
                    SELECT 1 FROM user_card_tags AS leg
                    WHERE leg.user_id = user_card_tags.user_id
                      AND leg.card_id = :legacy_id
                      AND leg.tag = user_card_tags.tag
                  )
                """
            ),
            {"legacy_id": legacy_id, "surrogate_id": surrogate_id},
        )
        session.execute(
            text("UPDATE user_card_tags SET card_id = :legacy_id WHERE card_id = :surrogate_id"),
            {"legacy_id": legacy_id, "surrogate_id": surrogate_id},
        )
        session.execute(
            text("UPDATE deck_cards SET card_id = :legacy_id WHERE card_id = :surrogate_id"),
            {"legacy_id": legacy_id, "surrogate_id": surrogate_id},
        )
        session.execute(
            text("UPDATE banlist_entries SET card_id = :legacy_id WHERE card_id = :surrogate_id"),
            {"legacy_id": legacy_id, "surrogate_id": surrogate_id},
        )
        session.execute(
            text(
                "UPDATE genesys_point_entries SET card_id = :legacy_id WHERE card_id = :surrogate_id"
            ),
            {"legacy_id": legacy_id, "surrogate_id": surrogate_id},
        )
        session.execute(
            text(
                """
                DELETE FROM card_format_legality
                WHERE card_id = :surrogate_id
                  AND format_code IN (
                    SELECT format_code FROM card_format_legality WHERE card_id = :legacy_id
                  )
                """
            ),
            {"legacy_id": legacy_id, "surrogate_id": surrogate_id},
        )
        session.execute(
            text(
                "UPDATE card_format_legality SET card_id = :legacy_id WHERE card_id = :surrogate_id"
            ),
            {"legacy_id": legacy_id, "surrogate_id": surrogate_id},
        )
        session.execute(
            text("UPDATE decks SET preview_card_id = :legacy_id WHERE preview_card_id = :surrogate_id"),
            {"legacy_id": legacy_id, "surrogate_id": surrogate_id},
        )
        session.execute(
            text("DELETE FROM cards WHERE id = :surrogate_id"),
            {"surrogate_id": surrogate_id},
        )


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


def refresh_collection_printing_links(session: Session) -> int:
    """Re-attach all collection_items to printings by set_code + rarity_code."""
    if is_postgres():
        result = session.execute(
            text(
                """
                UPDATE collection_items AS ci
                SET printing_id = p.id
                FROM printings AS p
                WHERE p.set_code = ci.set_code
                  AND p.set_rarity_code = ci.rarity_code
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
                WHERE EXISTS (
                    SELECT 1 FROM printings AS p
                    WHERE p.set_code = collection_items.set_code
                      AND p.set_rarity_code = collection_items.rarity_code
                )
                """
            )
        )
    return result.rowcount or 0


def normalize_rarity_codes_in_db(session: Session) -> dict[str, int]:
    """Canonicalize stored rarity codes and refresh collection printing links."""
    printing_updates = 0
    for printing in session.scalars(select(Printing)):
        resolved = resolve_rarity(printing.set_rarity_code or "")
        if resolved is None and printing.set_rarity:
            resolved = resolve_rarity(printing.set_rarity)
        if resolved is None:
            continue
        if printing.set_rarity_code != resolved.normalized_code:
            printing.set_rarity_code = resolved.normalized_code
            printing_updates += 1

    collection_updates = 0
    for item in session.scalars(select(CollectionItem)):
        resolved = resolve_rarity(item.rarity_code)
        if resolved is None:
            continue
        if item.rarity_code != resolved.normalized_code:
            item.rarity_code = resolved.normalized_code
            collection_updates += 1

    session.flush()
    relinked = refresh_collection_printing_links(session)
    return {
        "printings_updated": printing_updates,
        "collection_items_updated": collection_updates,
        "collection_links_refreshed": relinked,
    }


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


def _card_fields_from_api(entry: dict) -> dict:
    """Column values for a Card row (no id — assigned by the DB / upsert match).

    ``passcode`` falls back to the legacy ``id`` field for YGOProDeck-shaped
    entries; it is NULL for cards printed without a passcode.
    """
    images = entry.get("card_images") or [{}]
    img = images[0] if images else {}
    link_rating = _int_or_none(entry.get("link_rating"))
    pendulum_scale = _int_or_none(entry.get("pendulum_scale"))
    passcode = _int_or_none(entry.get("passcode", entry.get("id")))
    return {
        "passcode": passcode,
        "source_url": entry.get("source_url"),
        "name": entry.get("name", ""),
        "type": entry.get("type"),
        "human_readable_type": entry.get("humanReadableCardType"),
        "frame_type": entry.get("frameType"),
        "desc": entry.get("desc"),
        "atk": _int_or_none(entry.get("atk")),
        "def_": _int_or_none(entry.get("def")),
        "level": _int_or_none(entry.get("level")),
        "race": entry.get("race"),
        "attribute": entry.get("attribute"),
        "archetype": entry.get("archetype"),
        "character": entry.get("character"),
        "linkval": _int_or_none(entry.get("linkval")) or link_rating,
        "scale": _int_or_none(entry.get("scale")) or pendulum_scale,
        "category": entry.get("category"),
        "types": entry.get("types"),
        "mechanic": entry.get("mechanic"),
        "rank": _int_or_none(entry.get("rank")),
        "link_rating": link_rating,
        "pendulum_scale": pendulum_scale,
        "link_markers": entry.get("link_markers"),
        "summoning_condition": entry.get("summoning_condition"),
        "ygoprodeck_url": entry.get("ygoprodeck_url"),
        "image_url": img.get("image_url"),
        "image_url_small": img.get("image_url_small"),
        "has_errata": bool(entry.get("has_errata")),
        "last_erratum_date": _date_or_none(entry.get("last_erratum_date")),
        "tips": entry.get("tips"),
    }


def _card_natural_key(passcode: int | None, source_url: str | None) -> tuple[str, object] | None:
    """Upsert key: prefer passcode, else source_url; None when unidentifiable."""
    if passcode is not None:
        return ("p", passcode)
    if source_url:
        return ("u", source_url)
    return None


def _printing_rarity_code(card_set: dict) -> str:
    code_raw = (card_set.get("set_rarity_code") or "").strip()
    if code_raw:
        resolved = resolve_rarity(code_raw)
        if resolved is not None:
            return resolved.normalized_code
        return normalize_rarity_code(code_raw)
    label = (card_set.get("set_rarity") or "Unknown").strip()
    resolved = resolve_rarity(label)
    if resolved is not None:
        return resolved.normalized_code
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


def _date_or_none(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return parse_yugipedia_date(value)
    return None


def _resolve_erratum_release_date(
    session: Session,
    *,
    set_code: str | None,
    set_name: str | None,
    release_from_json: str | None,
    tcg_release_cache: dict[str, date | None],
) -> date | None:
    parsed = _date_or_none(release_from_json)
    if parsed:
        return parsed
    abbr = set_abbr_from_code(set_code)
    if abbr:
        if abbr not in tcg_release_cache:
            row = session.get(TcgSet, abbr)
            tcg_release_cache[abbr] = row.release_date if row else None
        if tcg_release_cache[abbr]:
            return tcg_release_cache[abbr]
    if set_name:
        for abbr_key, cached in tcg_release_cache.items():
            if cached is None:
                row = session.get(TcgSet, abbr_key)
                tcg_release_cache[abbr_key] = row.release_date if row else None
        for row in session.execute(select(TcgSet).where(TcgSet.name == set_name)).scalars():
            return row.release_date
    return None


def _errata_rows_for_entry(
    session: Session,
    card_id: int,
    entry: dict,
    tcg_release_cache: dict[str, date | None],
) -> list[CardErrataVersion]:
    rows: list[CardErrataVersion] = []
    for version in entry.get("errata") or []:
        if version.get("language", ERRATA_UI_LANGUAGE) != ERRATA_UI_LANGUAGE:
            continue
        release = _resolve_erratum_release_date(
            session,
            set_code=version.get("set_code"),
            set_name=version.get("set_name"),
            release_from_json=version.get("release_date"),
            tcg_release_cache=tcg_release_cache,
        )
        rows.append(
            CardErrataVersion(
                card_id=card_id,
                language=version.get("language") or "English",
                version_index=int(version.get("version_index", 0)),
                version_label=version.get("version_label") or "",
                lore_text=version.get("lore_text"),
                lore_html=version.get("lore_html"),
                set_code=version.get("set_code"),
                set_name=version.get("set_name"),
                release_date=release,
            )
        )
    return rows


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

        # Printings + errata are fully rebuilt from the scrape each run. Delete
        # them up front (collection links already detached), but KEEP card rows so
        # surrogate ids survive and the user data that references them
        # (decks/favorites/tags/preview/banlist/genesys/legality) is preserved.
        # Cards are upserted by natural key below; cards absent from this scrape are
        # intentionally not pruned.
        session.query(Printing).delete()
        session.query(CardErrataVersion).delete()
        session.commit()

        _prune_surrogate_passcode_duplicates(session)

        # Normalize entries once and compute each card's natural key.
        prepared: list[tuple[tuple[str, object], dict, dict]] = []
        seen_keys: set[tuple[str, object]] = set()
        for entry in entries:
            if "category" not in entry and entry.get("frameType") is not None:
                from ygo_app.yugipedia.card_import import enrich_ygopro_entry

                entry = enrich_ygopro_entry(entry)
            fields = _card_fields_from_api(entry)
            key = _card_natural_key(fields["passcode"], fields["source_url"])
            if key is None:
                continue
            if key in seen_keys:
                # Duplicate natural key within a scrape: keep the last occurrence.
                prepared = [p for p in prepared if p[0] != key]
            seen_keys.add(key)
            prepared.append((key, fields, entry))

        by_passcode_col, by_legacy_id, by_source_url = _load_card_key_maps(session)
        update_maps: list[dict] = []
        insert_maps: list[dict] = []
        for key, fields, _entry in prepared:
            cid = _resolve_existing_id(
                key=key,
                fields=fields,
                by_passcode_col=by_passcode_col,
                by_legacy_id=by_legacy_id,
                by_source_url=by_source_url,
            )
            if cid is not None:
                update_maps.append({"id": cid, **fields})
            else:
                insert_maps.append(fields)
        print(
            f"Upserting {len(update_maps)} cards (update) and {len(insert_maps)} cards (insert)...",
            flush=True,
        )

        for chunk in _chunked(update_maps, batch_size):
            session.bulk_update_mappings(Card, chunk)
        for chunk in _chunked(insert_maps, batch_size):
            session.bulk_insert_mappings(Card, chunk)
        session.commit()
        cards_imported = len(update_maps) + len(insert_maps)

        # Reload so newly inserted cards resolve to ids for their printings/errata.
        by_passcode_col, by_legacy_id, by_source_url = _load_card_key_maps(session)
        keymap = {
            **{("p", k): v for k, v in by_passcode_col.items()},
            **{("p", k): v for k, v in by_legacy_id.items()},
            **{("u", k): v for k, v in by_source_url.items()},
        }

        batch_printings: list[Printing] = []
        batch_errata: list[CardErrataVersion] = []
        tcg_release_cache: dict[str, date | None] = {}

        def _flush_children() -> None:
            nonlocal printings_imported
            if batch_printings or batch_errata:
                session.add_all(batch_printings)
                session.add_all(batch_errata)
                session.commit()
            printings_imported += len(batch_printings)
            batch_printings.clear()
            batch_errata.clear()

        for key, _fields, entry in tqdm(prepared, desc="Importing cards"):
            card_id = keymap.get(key)
            if card_id is None:
                continue
            batch_errata.extend(
                _errata_rows_for_entry(session, card_id, entry, tcg_release_cache)
            )
            seen_printings: set[tuple[str, str]] = set()
            for cs in entry.get("card_sets") or []:
                set_code = cs.get("set_code")
                if not set_code:
                    continue
                rarity_code = _printing_rarity_code(cs)
                pkey = (set_code, rarity_code)
                if pkey in seen_printings:
                    continue
                seen_printings.add(pkey)
                batch_printings.append(
                    Printing(
                        card_id=card_id,
                        set_name=cs.get("set_name"),
                        set_code=set_code,
                        set_rarity=cs.get("set_rarity"),
                        set_rarity_code=rarity_code,
                        set_price=cs.get("set_price"),
                    )
                )
            if len(batch_printings) >= batch_size:
                _flush_children()

        _flush_children()

        from ygo_app.release_dates import refresh_card_latest_release_dates

        refresh_card_latest_release_dates(session)

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


def _link_printing(session: Session, set_code: str, rarity_raw: str) -> int | None:
    for variant in rarity_match_variants(rarity_raw):
        stmt = (
            select(Printing.id)
            .where(Printing.set_code == set_code)
            .where(Printing.set_rarity_code == variant)
            .limit(1)
        )
        row = session.execute(stmt).first()
        if row is not None:
            return row[0]
    return None


def _lookup_printing_id_cached(
    set_code: str,
    rarity_raw: str,
    printing_by_key: dict[tuple[str, str], int],
) -> int | None:
    for variant in rarity_match_variants(rarity_raw):
        printing_id = printing_by_key.get((set_code, variant))
        if printing_id is not None:
            return printing_id
    return None


def _match_printing(
    session: Session, set_code: str, rarity_raw: str
) -> tuple[int | None, str | None]:
    if not set_code:
        return None, "Missing card number"
    resolved = resolve_rarity(rarity_raw)
    if (rarity_raw or "").strip() and resolved is None:
        return None, f"Unknown rarity '{rarity_display(normalize_rarity_code(rarity_raw))}'"
    printing_id = _link_printing(session, set_code, rarity_raw)
    if printing_id is not None:
        return printing_id, None
    has_set = session.execute(
        select(Printing.id).where(Printing.set_code == set_code).limit(1)
    ).scalar()
    if has_set:
        label = rarity_label_for_error(rarity_raw, resolved)
        return None, (
            f"Rarity '{label}' not found for set code '{set_code}'"
        )
    return None, f"Set code '{set_code}' not found in catalog"


def _nonempty(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _match_printing_cached(
    set_code: str,
    rarity_raw: str,
    printing_by_key: dict[tuple[str, str], int],
    catalog_set_codes: set[str],
) -> tuple[int | None, str | None]:
    if not set_code:
        return None, "Missing card number"
    resolved = resolve_rarity(rarity_raw)
    if (rarity_raw or "").strip() and resolved is None:
        return None, f"Unknown rarity '{rarity_display(normalize_rarity_code(rarity_raw))}'"
    printing_id = _lookup_printing_id_cached(set_code, rarity_raw, printing_by_key)
    if printing_id is not None:
        return printing_id, None
    if set_code in catalog_set_codes:
        label = rarity_label_for_error(rarity_raw, resolved)
        return None, (
            f"Rarity '{label}' not found for set code '{set_code}'"
        )
    return None, f"Set code '{set_code}' not found in catalog"


def _chunked(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


@dataclass
class CollectionImportResult:
    imported: int
    merged: int = 0
    rejected: list[dict] = field(default_factory=list)
    fieldnames: list[str] = field(default_factory=list)


def import_collection_csv(
    path: Path | str,
    *,
    user_id: int,
    replace: bool = True,
    progress_callback: Callable[[int, int], None] | None = None,
) -> CollectionImportResult:
    from ygo_app.models import CollectionItemFolder

    path = Path(path)
    init_db()
    # expire_on_commit=False keeps preloaded lookup objects usable after the
    # periodic mid-loop commits, so append does not re-query the DB per row.
    session = SessionLocal(expire_on_commit=False)
    imported = 0
    merged = 0
    rejected: list[dict] = []
    output_fieldnames: list[str] = []

    # Per-user caches populated before the row loop to avoid per-row round-trips
    # (critical on remote Postgres where each query is a network hop).
    existing_by_key: dict[tuple[str, str], CollectionItem] = {}
    printing_by_key: dict[tuple[str, str], int] = {}
    catalog_set_codes: set[str] = set()
    folder_cache: dict[str, "object"] = {}

    # New items created during this import (pending ORM, mutated in memory for
    # CSV-internal dedup; inserted in one batched flush at the end).
    new_by_key: dict[tuple[str, str], CollectionItem] = {}
    # Bulk-write accumulators for merges into pre-existing DB rows, applied once
    # after the loop so remote Postgres sees batched statements, not per-row I/O.
    alloc_index: dict[tuple[int, int | None], CollectionItemFolder] = {}
    item_update_final: dict[int, dict] = {}
    alloc_update_final: dict[int, int] = {}
    alloc_insert_final: dict[tuple[int, int | None], int] = {}

    _ITEM_MERGE_FIELDS = (
        "quantity",
        "trade_quantity",
        "condition",
        "edition",
        "language",
        "price_bought",
        "date_bought",
        "notes",
    )

    def _item_state(item: CollectionItem) -> dict:
        state = item_update_final.get(item.id)
        if state is None:
            state = {field: getattr(item, field) for field in _ITEM_MERGE_FIELDS}
            item_update_final[item.id] = state
        return state

    def _folder_for(name_raw: str):
        from ygo_app.services import get_or_create_folder

        if name_raw in folder_cache:
            return folder_cache[name_raw]
        try:
            folder = get_or_create_folder(session, user_id, name_raw)
        except ValueError:
            folder = None
        folder_cache[name_raw] = folder
        return folder

    def _merge_folder_allocation(
        item: CollectionItem,
        *,
        folder,
        quantity: int,
    ) -> None:
        folder_id = folder.id if folder else None
        for alloc in item.folder_allocations:
            if alloc.folder_id == folder_id:
                alloc.quantity += quantity
                return
        item.folder_allocations.append(
            CollectionItemFolder(folder_id=folder_id, quantity=quantity)
        )

    def _merge_existing_item(
        item: CollectionItem,
        row: dict,
        *,
        quantity: int,
        folder,
    ) -> None:
        item.quantity += quantity
        item.trade_quantity += int(row.get("Trade Quantity") or 0)
        if condition := _nonempty(row.get("Condition")):
            item.condition = condition
        if edition := _nonempty(row.get("Printing")):
            item.edition = edition
        if language := _nonempty(row.get("Language")):
            item.language = language
        if price_bought := _float_or_none(row.get("Price Bought")):
            item.price_bought = price_bought
        if date_bought := _nonempty(row.get("Date Bought")):
            item.date_bought = date_bought
        if notes := _nonempty(row.get("Notes")):
            item.notes = notes
        folder_raw = (row.get("Folder Name") or "").strip()
        if folder_raw:
            _merge_folder_allocation(item, folder=folder, quantity=quantity)

    def _merge_existing_bulk(
        item: CollectionItem,
        row: dict,
        *,
        quantity: int,
        folder,
    ) -> None:
        state = _item_state(item)
        state["quantity"] += quantity
        state["trade_quantity"] += int(row.get("Trade Quantity") or 0)
        if condition := _nonempty(row.get("Condition")):
            state["condition"] = condition
        if edition := _nonempty(row.get("Printing")):
            state["edition"] = edition
        if language := _nonempty(row.get("Language")):
            state["language"] = language
        if price_bought := _float_or_none(row.get("Price Bought")):
            state["price_bought"] = price_bought
        if date_bought := _nonempty(row.get("Date Bought")):
            state["date_bought"] = date_bought
        if notes := _nonempty(row.get("Notes")):
            state["notes"] = notes
        folder_raw = (row.get("Folder Name") or "").strip()
        if not folder_raw:
            return
        folder_id = folder.id if folder else None
        alloc = alloc_index.get((item.id, folder_id))
        if alloc is not None:
            alloc_update_final[alloc.id] = (
                alloc_update_final.get(alloc.id, alloc.quantity) + quantity
            )
        else:
            key = (item.id, folder_id)
            alloc_insert_final[key] = alloc_insert_final.get(key, 0) + quantity

    def _process_row(row: dict) -> None:
        nonlocal imported, merged
        set_code = (row.get("Card Number") or "").strip()
        rarity_raw = (row.get("Rarity") or "").strip()
        resolved = resolve_rarity(rarity_raw)
        if rarity_raw and resolved is None:
            rejected.append(
                {
                    **row,
                    IMPORT_ERROR_COLUMN: (
                        f"Unknown rarity '{rarity_display(normalize_rarity_code(rarity_raw))}'"
                    ),
                }
            )
            return
        rarity_code = (
            resolved.normalized_code
            if resolved is not None
            else normalize_rarity_code(rarity_raw)
        )
        printing_id, reason = _match_printing_cached(
            set_code, rarity_raw, printing_by_key, catalog_set_codes
        )
        if reason:
            rejected.append({**row, IMPORT_ERROR_COLUMN: reason})
            return

        quantity = int(row.get("Quantity") or 1)
        folder_raw = (row.get("Folder Name") or "").strip()
        folder = _folder_for(folder_raw) if folder_raw else None
        key = (set_code, rarity_code)

        if not replace:
            existing = existing_by_key.get(key)
            if existing is not None:
                _merge_existing_bulk(existing, row, quantity=quantity, folder=folder)
                merged += 1
                return

        pending = new_by_key.get(key)
        if pending is not None:
            _merge_existing_item(pending, row, quantity=quantity, folder=folder)
            merged += 1
            return

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
            notes=_nonempty(row.get("Notes")),
            sell_price=None,
            printing_id=printing_id,
        )
        item.folder_allocations.append(
            CollectionItemFolder(
                folder_id=folder.id if folder else None,
                quantity=quantity,
            )
        )
        session.add(item)
        new_by_key[key] = item
        imported += 1

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

        # Preload printing match map for every set code referenced in the CSV.
        wanted_set_codes = sorted(
            {
                (row.get("Card Number") or "").strip()
                for row in rows
                if (row.get("Card Number") or "").strip()
            }
        )
        for chunk in _chunked(wanted_set_codes, 1000):
            for sc, rc, sr, pid in session.execute(
                select(
                    Printing.set_code,
                    Printing.set_rarity_code,
                    Printing.set_rarity,
                    Printing.id,
                ).where(Printing.set_code.in_(chunk))
            ).all():
                catalog_set_codes.add(sc)
                for variant in variants_for_printing(rc, sr):
                    printing_by_key.setdefault((sc, variant), pid)

        # Preload the user's existing collection (with folder allocations) so
        # append merges happen in memory instead of one query per row.
        if not replace:
            for item in (
                session.execute(
                    select(CollectionItem)
                    .options(joinedload(CollectionItem.folder_allocations))
                    .where(CollectionItem.user_id == user_id)
                    .order_by(CollectionItem.id)
                )
                .unique()
                .scalars()
                .all()
            ):
                existing_by_key.setdefault((item.set_code, item.rarity_code), item)
                for alloc in item.folder_allocations:
                    alloc_index[(item.id, alloc.folder_id)] = alloc
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

        # Insert all new items (and their allocations) in one batched flush.
        session.flush()

        # Apply merges into pre-existing rows as batched bulk statements.
        if item_update_final:
            session.bulk_update_mappings(
                CollectionItem,
                [{"id": item_id, **values} for item_id, values in item_update_final.items()],
            )
        if alloc_update_final:
            session.bulk_update_mappings(
                CollectionItemFolder,
                [{"id": alloc_id, "quantity": qty} for alloc_id, qty in alloc_update_final.items()],
            )
        if alloc_insert_final:
            session.bulk_insert_mappings(
                CollectionItemFolder,
                [
                    {"collection_item_id": item_id, "folder_id": folder_id, "quantity": qty}
                    for (item_id, folder_id), qty in alloc_insert_final.items()
                ],
            )

        if progress_callback is not None and total > 0:
            progress_callback(total, total)

        session.commit()
        return CollectionImportResult(
            imported=imported,
            merged=merged,
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
