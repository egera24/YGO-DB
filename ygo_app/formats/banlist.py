"""Banlist resolution and card status lookup."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ygo_app.formats.base import FormatRules
from ygo_app.models import BanlistEntry, BanlistRevision

STATUS_FORBIDDEN = "forbidden"
STATUS_LIMITED = "limited"
STATUS_SEMI_LIMITED = "semi_limited"


def resolve_banlist_revision(
    session: Session,
    rules: FormatRules,
    revision_id: int | None,
) -> BanlistRevision | None:
    if rules.banlist_mode == "none":
        return None

    if revision_id is not None and rules.banlist_selectable:
        return session.get(BanlistRevision, revision_id)

    if rules.fixed_banlist_label:
        return session.execute(
            select(BanlistRevision)
            .where(BanlistRevision.label == rules.fixed_banlist_label)
            .order_by(desc(BanlistRevision.effective_from))
            .limit(1)
        ).scalar_one_or_none()

    return session.execute(
        select(BanlistRevision)
        .where(BanlistRevision.source_list_id == "current")
        .order_by(desc(BanlistRevision.fetched_at))
        .limit(1)
    ).scalar_one_or_none()


def load_banlist_map(
    session: Session,
    revision: BanlistRevision | None,
) -> dict[int, str]:
    if not revision:
        return {}
    rows = session.execute(
        select(BanlistEntry.card_id, BanlistEntry.status).where(
            BanlistEntry.revision_id == revision.id,
            BanlistEntry.card_id.is_not(None),
        )
    ).all()
    return {int(card_id): status for card_id, status in rows if card_id is not None}


def effective_max_copies(status: str | None, rules: FormatRules) -> int:
    if status is None:
        return rules.max_copies_default
    if status == STATUS_FORBIDDEN:
        if rules.banlist_mode == "traditional":
            return 1
        return 0
    if status == STATUS_LIMITED:
        return 1
    if status == STATUS_SEMI_LIMITED:
        return 2
    return rules.max_copies_default


def banlist_status_label(status: str | None) -> str | None:
    if status == STATUS_FORBIDDEN:
        return "Forbidden"
    if status == STATUS_LIMITED:
        return "Limited"
    if status == STATUS_SEMI_LIMITED:
        return "Semi-Limited"
    return None
