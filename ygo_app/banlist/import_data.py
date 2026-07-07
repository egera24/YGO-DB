"""Upsert banlist revisions into the database."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ygo_app.banlist.match import build_card_name_index, match_card_id
from ygo_app.models import BanlistEntry, BanlistRevision


def upsert_banlist_revision(
    session: Session,
    revision_data: dict,
    *,
    card_index: dict[str, list[int]] | None = None,
) -> tuple[BanlistRevision, int, int]:
    if card_index is None:
        card_index = build_card_name_index(session)

    existing = session.execute(
        select(BanlistRevision).where(
            BanlistRevision.source_list_id == revision_data["source_list_id"]
        )
    ).scalar_one_or_none()

    now = datetime.utcnow()
    if existing:
        revision = existing
        revision.label = revision_data["label"]
        revision.effective_from = revision_data.get("effective_from")
        revision.source_url = revision_data.get("source_url")
        revision.fetched_at = now
        session.execute(delete(BanlistEntry).where(BanlistEntry.revision_id == revision.id))
    else:
        revision = BanlistRevision(
            source_list_id=revision_data["source_list_id"],
            label=revision_data["label"],
            effective_from=revision_data.get("effective_from"),
            source_url=revision_data.get("source_url"),
            fetched_at=now,
        )
        session.add(revision)
        session.flush()

    matched = 0
    unmatched = 0
    for entry in revision_data.get("entries", []):
        card_id = match_card_id(entry["card_name_raw"], card_index)
        if card_id:
            matched += 1
        else:
            unmatched += 1
        session.add(
            BanlistEntry(
                revision_id=revision.id,
                card_id=card_id,
                card_name_raw=entry["card_name_raw"],
                konami_cid=entry.get("konami_cid"),
                status=entry["status"],
            )
        )

    session.commit()
    return revision, matched, unmatched
