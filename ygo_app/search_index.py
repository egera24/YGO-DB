"""Dialect-aware full-text search helpers (SQLite FTS5 vs PostgreSQL tsvector)."""

from __future__ import annotations

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from ygo_app.database import is_postgres, is_sqlite
from ygo_app.models import Card


def ensure_search_index(conn) -> None:
    """Create SQLite FTS5 virtual table if needed."""
    if not is_sqlite():
        return
    conn.execute(
        text(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
                name, desc, archetype, type, race
            )
            """
        )
    )
    conn.commit()


def rebuild_search_index(session: Session) -> None:
    if is_sqlite():
        session.execute(text("DELETE FROM cards_fts"))
        session.execute(
            text(
                """
                INSERT INTO cards_fts(rowid, name, desc, archetype, type, race)
                SELECT id, name, COALESCE(desc,''), COALESCE(archetype,''),
                       COALESCE(type,''), COALESCE(race,'')
                FROM cards
                """
            )
        )
    # PostgreSQL uses on-the-fly to_tsvector in queries; no separate index table.


def fts_card_ids(session: Session, term: str, *, limit: int) -> list[int] | None:
    """
    Return matching card IDs for a text query, or None to fall back to ILIKE.
    """
    stripped = term.strip()
    if not stripped or stripped.isdigit():
        return None

    if is_sqlite():
        fts_query = " ".join(f'"{part}"' for part in stripped.split() if part)
        ids = (
            session.execute(
                text(
                    "SELECT rowid FROM cards_fts WHERE cards_fts MATCH :q "
                    "ORDER BY rank LIMIT :lim"
                ),
                {"q": fts_query, "lim": limit},
            )
            .scalars()
            .all()
        )
        return list(ids) if ids else None

    if is_postgres():
        ids = (
            session.execute(
                text(
                    """
                    SELECT id FROM cards
                    WHERE to_tsvector(
                        'english',
                        coalesce(name, '') || ' ' ||
                        coalesce("desc", '') || ' ' ||
                        coalesce(archetype, '') || ' ' ||
                        coalesce(type, '') || ' ' ||
                        coalesce(race, '')
                    ) @@ plainto_tsquery('english', :q)
                    ORDER BY name
                    LIMIT :lim
                    """
                ),
                {"q": stripped, "lim": limit},
            )
            .scalars()
            .all()
        )
        return list(ids) if ids else None

    return None


def ilike_text_filter(term: str):
    like = f"%{term.strip()}%"
    return or_(
        Card.name.ilike(like),
        Card.desc.ilike(like),
        Card.archetype.ilike(like),
    )
