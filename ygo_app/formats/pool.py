"""Card pool and printing eligibility helpers."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ygo_app.formats.base import FormatRules
from ygo_app.models import Card, CardFormatLegality, Printing, TcgSet


def expansion_abbr_from_set_code(set_code: str) -> str | None:
    if not set_code:
        return None
    parts = set_code.split("-")
    if len(parts) >= 2:
        return parts[0].upper()
    return None


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


def card_legal_in_format(session: Session, card: Card, rules: FormatRules) -> bool:
    if rules.pool_uses_legality_table:
        row = session.execute(
            select(CardFormatLegality.is_legal).where(
                CardFormatLegality.card_id == card.id,
                CardFormatLegality.format_code == rules.code,
            )
        ).scalar_one_or_none()
        if row is not None:
            return bool(row)
        return False

    if rules.pool_cutoff_date:
        return card_in_pool_by_cutoff(session, card.id, rules.pool_cutoff_date)

    return True


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


def format_pool_card_ids_subquery(session: Session, rules: FormatRules):
    if rules.pool_uses_legality_table:
        return select(CardFormatLegality.card_id).where(
            CardFormatLegality.format_code == rules.code,
            CardFormatLegality.is_legal.is_(True),
        )
    return None


def card_ids_in_pool(session: Session, rules: FormatRules) -> set[int] | None:
    subq = format_pool_card_ids_subquery(session, rules)
    if subq is None:
        return None
    return set(session.execute(subq).scalars().all())
