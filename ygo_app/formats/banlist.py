"""Banlist resolution and card status lookup."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ygo_app.formats.base import FormatRules
from ygo_app.models import BanlistEntry, BanlistRevision

STATUS_FORBIDDEN = "forbidden"
STATUS_LIMITED = "limited"
STATUS_SEMI_LIMITED = "semi_limited"
STATUS_UNLIMITED = "unlimited"

_VALID_STATUSES = frozenset({STATUS_FORBIDDEN, STATUS_LIMITED, STATUS_SEMI_LIMITED})
_FILTER_TOKENS = _VALID_STATUSES | {STATUS_UNLIMITED}

_STATUS_ALIASES: dict[str, str] = {
    "forbidden": STATUS_FORBIDDEN,
    "limited": STATUS_LIMITED,
    "semi_limited": STATUS_SEMI_LIMITED,
    "semi-limited": STATUS_SEMI_LIMITED,
    "semilimited": STATUS_SEMI_LIMITED,
    "unlimited": STATUS_UNLIMITED,
    "unrestricted": STATUS_UNLIMITED,
    "notonlist": STATUS_UNLIMITED,
    "not-on-list": STATUS_UNLIMITED,
}


def parse_banlist_status_param(value: str | None) -> list[str]:
    """Parse comma-separated banlist status filter tokens into filter values."""
    if not value or not value.strip():
        return []
    seen: set[str] = set()
    result: list[str] = []
    for chunk in value.split(","):
        token = chunk.strip()
        if not token:
            continue
        normalized = _STATUS_ALIASES.get(token.lower().replace(" ", ""), token.lower())
        if normalized in _FILTER_TOKENS and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def partition_banlist_status_filters(
    statuses: list[str],
) -> tuple[list[str], bool]:
    """Split parsed filter tokens into DB statuses and unlimited flag."""
    restricted = [s for s in statuses if s != STATUS_UNLIMITED]
    include_unlimited = STATUS_UNLIMITED in statuses
    return restricted, include_unlimited


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


def effective_banlist_status(status: str | None, rules: FormatRules) -> str | None:
    """Return restriction status as seen in the given format."""
    if status == STATUS_FORBIDDEN and rules.banlist_mode == "traditional":
        return STATUS_LIMITED
    return status


def db_statuses_for_effective_filters(
    effective_statuses: list[str],
    rules: FormatRules,
) -> list[str]:
    """Map user-facing restriction filters to raw banlist DB statuses."""
    db_statuses: set[str] = set()
    for status in effective_statuses:
        if status == STATUS_FORBIDDEN:
            if rules.banlist_mode != "traditional":
                db_statuses.add(STATUS_FORBIDDEN)
        elif status == STATUS_LIMITED:
            db_statuses.add(STATUS_LIMITED)
            if rules.banlist_mode == "traditional":
                db_statuses.add(STATUS_FORBIDDEN)
        elif status == STATUS_SEMI_LIMITED:
            db_statuses.add(STATUS_SEMI_LIMITED)
    return sorted(db_statuses)


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


def banlist_status_label(status: str | None, rules: FormatRules | None = None) -> str | None:
    if rules is not None:
        status = effective_banlist_status(status, rules)
    if status == STATUS_FORBIDDEN:
        return "Forbidden"
    if status == STATUS_LIMITED:
        return "Limited"
    if status == STATUS_SEMI_LIMITED:
        return "Semi-Limited"
    return None
