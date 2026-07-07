"""Match banlist card names to catalog passcodes."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ygo_app.cardmarket.catalog.normalize import normalize_card_name
from ygo_app.models import Card


def build_card_name_index(session: Session) -> dict[str, list[int]]:
    rows = session.execute(select(Card.id, Card.name)).all()
    index: dict[str, list[int]] = defaultdict(list)
    for card_id, name in rows:
        index[normalize_card_name(name)].append(int(card_id))
    return index


def match_card_id(card_name: str, index: dict[str, list[int]]) -> int | None:
    key = normalize_card_name(card_name)
    matches = index.get(key, [])
    if len(matches) == 1:
        return matches[0]
    return None
