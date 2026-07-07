"""Upsert Genesys point lists into the database."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ygo_app.banlist.match import build_card_name_index, match_card_id
from ygo_app.models import GenesysPointEntry, GenesysPointList


def upsert_point_list(
    session: Session,
    list_data: dict,
    *,
    card_index: dict[str, list[int]] | None = None,
) -> tuple[GenesysPointList, int, int]:
    if card_index is None:
        card_index = build_card_name_index(session)

    existing = session.execute(
        select(GenesysPointList).where(GenesysPointList.source_url == list_data["source_url"])
    ).scalar_one_or_none()

    now = datetime.utcnow()
    if existing:
        point_list = existing
        point_list.label = list_data["label"]
        point_list.effective_from = list_data["effective_from"]
        point_list.fetched_at = now
        session.execute(
            delete(GenesysPointEntry).where(GenesysPointEntry.list_id == point_list.id)
        )
    else:
        point_list = GenesysPointList(
            label=list_data["label"],
            effective_from=list_data["effective_from"],
            source_url=list_data["source_url"],
            fetched_at=now,
        )
        session.add(point_list)
        session.flush()

    matched = 0
    unmatched = 0
    for entry in list_data.get("entries", []):
        card_id = match_card_id(entry["card_name_raw"], card_index)
        if card_id:
            matched += 1
        else:
            unmatched += 1
        session.add(
            GenesysPointEntry(
                list_id=point_list.id,
                card_id=card_id,
                card_name_raw=entry["card_name_raw"],
                points=entry["points"],
            )
        )

    session.commit()
    return point_list, matched, unmatched
