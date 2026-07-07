"""Card pool and printing eligibility helpers."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import delete, distinct, exists, func, select
from sqlalchemy.orm import Session

from ygo_app.formats.base import FormatRules
from ygo_app.models import Card, CardFormatLegality, Printing, TcgSet

logger = logging.getLogger(__name__)


def expansion_abbr_from_set_code(set_code: str) -> str | None:
    if not set_code:
        return None
    parts = set_code.split("-")
    if len(parts) >= 2:
        return parts[0].upper()
    return None


def legal_card_ids_by_cutoff(session: Session, cutoff: date) -> set[int]:
    """Python cutoff pool — offline jobs and SQLite tests only."""
    printing_rows = session.execute(select(Printing.card_id, Printing.set_code)).all()
    tcg_sets = {row.abbr: row for row in session.execute(select(TcgSet)).scalars().all()}
    legal_ids: set[int] = set()
    for card_id, set_code in printing_rows:
        abbr = expansion_abbr_from_set_code(set_code or "")
        if not abbr:
            continue
        tcg_set = tcg_sets.get(abbr)
        if tcg_set and tcg_set.release_date and tcg_set.release_date <= cutoff:
            legal_ids.add(int(card_id))
    return legal_ids


def legal_card_ids_by_cutoff_sql(session: Session, cutoff: date):
    """SQL cutoff pool for offline refresh jobs (PostgreSQL)."""
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        abbr_expr = func.upper(func.split_part(Printing.set_code, "-", 1))
        return (
            select(distinct(Printing.card_id))
            .join(TcgSet, TcgSet.abbr == abbr_expr)
            .where(
                TcgSet.release_date.is_not(None),
                TcgSet.release_date <= cutoff,
            )
        )
    legal_ids = legal_card_ids_by_cutoff(session, cutoff)
    if not legal_ids:
        return select(Card.id).where(Card.id < 0)
    return select(Card.id).where(Card.id.in_(legal_ids))


def card_in_pool_by_cutoff(session: Session, card_id: int, cutoff: date) -> bool:
    rows = session.execute(
        select(Printing.set_code, Printing.set_name).where(Printing.card_id == card_id)
    ).all()
    for set_code, set_name in rows:
        abbr = expansion_abbr_from_set_code(set_code or "")
        if abbr:
            tcg_set = session.get(TcgSet, abbr)
            if tcg_set and tcg_set.release_date and tcg_set.release_date <= cutoff:
                return True
    return False


def format_pool_legality_exists(format_code: str):
    """Semi-join filter: card is legal in the precomputed format pool."""
    return exists(
        select(1).where(
            CardFormatLegality.card_id == Card.id,
            CardFormatLegality.format_code == format_code,
            CardFormatLegality.is_legal.is_(True),
        )
    )


def warn_if_legality_table_empty(session: Session, rules: FormatRules) -> None:
    if not rules.pool_uses_legality_table:
        return
    row = session.execute(
        select(CardFormatLegality.card_id)
        .where(
            CardFormatLegality.format_code == rules.code,
            CardFormatLegality.is_legal.is_(True),
        )
        .limit(1)
    ).first()
    if row is None:
        logger.warning(
            "card_format_legality has no rows for format %r; "
            "run: python -m ygo_app.jobs.refresh_format_legality",
            rules.code,
        )


def format_pool_card_ids_subquery(session: Session, rules: FormatRules):
    """Subquery of legal card IDs from precomputed table. No runtime Python fallback."""
    if not rules.pool_uses_legality_table:
        return None
    warn_if_legality_table_empty(session, rules)
    return select(CardFormatLegality.card_id).where(
        CardFormatLegality.format_code == rules.code,
        CardFormatLegality.is_legal.is_(True),
    )


def card_ids_in_pool(session: Session, rules: FormatRules) -> set[int] | None:
    subq = format_pool_card_ids_subquery(session, rules)
    if subq is None:
        return None
    return set(session.execute(subq).scalars().all())


def batch_card_legal_in_format(
    session: Session, card_ids: list[int], rules: FormatRules
) -> dict[int, bool]:
    if not card_ids:
        return {}
    if rules.pool_uses_legality_table:
        rows = session.execute(
            select(CardFormatLegality.card_id, CardFormatLegality.is_legal).where(
                CardFormatLegality.format_code == rules.code,
                CardFormatLegality.card_id.in_(card_ids),
            )
        ).all()
        known = {int(cid): bool(legal) for cid, legal in rows}
        result: dict[int, bool] = {}
        for cid in card_ids:
            if cid in known:
                result[cid] = known[cid]
            elif rules.pool_cutoff_date:
                result[cid] = card_in_pool_by_cutoff(session, cid, rules.pool_cutoff_date)
            else:
                result[cid] = False
        return result
    if rules.pool_cutoff_date:
        return {
            cid: card_in_pool_by_cutoff(session, cid, rules.pool_cutoff_date)
            for cid in card_ids
        }
    return {cid: True for cid in card_ids}


def card_legal_in_format(session: Session, card: Card, rules: FormatRules) -> bool:
    return batch_card_legal_in_format(session, [card.id], rules).get(card.id, False)


def printing_legal_in_format(
    session: Session,
    printing: Printing,
    rules: FormatRules,
) -> bool:
    if rules.code == "speed_duel":
        return bool(printing.set_name and "speed duel" in printing.set_name.lower())

    if rules.pool_cutoff_date:
        abbr = expansion_abbr_from_set_code(printing.set_code)
        if abbr:
            tcg_set = session.get(TcgSet, abbr)
            if tcg_set and tcg_set.release_date:
                return tcg_set.release_date <= rules.pool_cutoff_date
        return False

    return True
