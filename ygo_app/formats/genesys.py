"""Genesys point list resolution."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ygo_app.models import GenesysPointEntry, GenesysPointList


def resolve_genesys_point_list(
    session: Session,
    list_id: int | None,
) -> GenesysPointList | None:
    if list_id is not None:
        return session.get(GenesysPointList, list_id)
    return session.execute(
        select(GenesysPointList).order_by(desc(GenesysPointList.effective_from)).limit(1)
    ).scalar_one_or_none()


def load_genesys_points_map(
    session: Session,
    point_list: GenesysPointList | None,
) -> dict[int, int]:
    if not point_list:
        return {}
    rows = session.execute(
        select(GenesysPointEntry.card_id, GenesysPointEntry.points).where(
            GenesysPointEntry.list_id == point_list.id,
            GenesysPointEntry.card_id.is_not(None),
        )
    ).all()
    return {int(card_id): int(points) for card_id, points in rows if card_id is not None}


def card_point_value(card_id: int, points_map: dict[int, int]) -> int:
    return points_map.get(card_id, 0)
