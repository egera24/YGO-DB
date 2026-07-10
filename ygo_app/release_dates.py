"""Refresh denormalized card latest_release_date from printings and tcg_sets."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from ygo_app.formats.pool import expansion_abbr_from_set_code
from ygo_app.models import Card, Printing, TcgSet

_POSTGRES_REFRESH_SQL = """
UPDATE cards c
SET latest_release_date = sub.max_date
FROM (
    SELECT p.card_id, MAX(t.release_date) AS max_date
    FROM printings p
    JOIN tcg_sets t ON t.abbr = UPPER(SPLIT_PART(p.set_code, '-', 1))
    WHERE t.release_date IS NOT NULL
    GROUP BY p.card_id
) sub
WHERE c.id = sub.card_id
"""


def refresh_card_latest_release_dates(session: Session) -> int:
    """Recompute cards.latest_release_date for all cards. Caller commits."""
    dialect = session.get_bind().dialect.name
    session.execute(update(Card).values(latest_release_date=None))
    if dialect == "postgresql":
        result = session.execute(text(_POSTGRES_REFRESH_SQL))
        return int(result.rowcount or 0)
    return _refresh_python(session)


def _refresh_python(session: Session) -> int:
    tcg_sets = {
        row.abbr: row.release_date
        for row in session.execute(select(TcgSet)).scalars()
        if row.release_date is not None
    }
    printing_rows = session.execute(select(Printing.card_id, Printing.set_code)).all()
    card_max: dict[int, date] = {}
    for card_id, set_code in printing_rows:
        abbr = expansion_abbr_from_set_code(set_code or "")
        if not abbr:
            continue
        release_date = tcg_sets.get(abbr)
        if release_date is None:
            continue
        prev = card_max.get(card_id)
        if prev is None or release_date > prev:
            card_max[card_id] = release_date

    updated = 0
    for card_id, max_date in card_max.items():
        session.execute(
            update(Card).where(Card.id == card_id).values(latest_release_date=max_date)
        )
        updated += 1
    return updated
