"""SQL helpers for Yugipedia-native card search filters."""

from __future__ import annotations

import json

from sqlalchemy import and_, or_

from ygo_app.models import Card


def parse_multi_param(value: str | None) -> list[str]:
    if not value or not value.strip():
        return []
    parts: list[str] = []
    for chunk in value.split(","):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts


def types_overlap_filter(selected: list[str]):
    """OR: card types JSON array contains any selected label."""
    if not selected:
        return None
    clauses = [Card.types.like(f'%"{t.replace(chr(34), "")}"%') for t in selected]
    return or_(*clauses)


def link_markers_contain_all(selected: list[str]):
    """AND: every selected marker appears in link_markers JSON."""
    if not selected:
        return None
    clauses = [Card.link_markers.like(f'%"{m.replace(chr(34), "")}"%') for m in selected]
    return clauses


def parse_mechanic_param(value: str | None) -> list[str]:
    """Split mechanic filter selections on | (composite values may contain commas)."""
    if not value or not value.strip():
        return []
    parts: list[str] = []
    for chunk in value.split("|"):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts


def _mechanic_token_clause(m: str):
    """Match a single mechanic token in a comma-space-separated mechanic field."""
    return or_(
        Card.mechanic == m,
        Card.mechanic.like(f"{m}, %"),
        Card.mechanic.like(f"%, {m}"),
        Card.mechanic.like(f"%, {m}, %"),
    )


def mechanic_filter(value: str | None):
    """Composite dropdown value (contains ', ') → AND; multiple selections → OR."""
    selections = parse_mechanic_param(value)
    if not selections:
        return None
    if len(selections) == 1:
        sel = selections[0]
        if ", " in sel:
            tokens = [t.strip() for t in sel.split(",") if t.strip()]
            return and_(*[_mechanic_token_clause(t) for t in tokens])
        return _mechanic_token_clause(sel)
    return or_(*[_mechanic_token_clause(s) for s in selections])


def parse_json_string_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data]
    except json.JSONDecodeError:
        pass
    return []


def card_types_list(card: Card) -> list[str]:
    return parse_json_string_list(card.types)


def card_link_markers_list(card: Card) -> list[str]:
    return parse_json_string_list(card.link_markers)


def card_response_extras(card: Card) -> dict:
    """Parsed list fields and resolved numeric aliases for API responses."""
    return {
        "types": card_types_list(card),
        "link_markers": card_link_markers_list(card),
        "link_rating": card.link_rating if card.link_rating is not None else card.linkval,
        "pendulum_scale": card.pendulum_scale
        if card.pendulum_scale is not None
        else card.scale,
    }
