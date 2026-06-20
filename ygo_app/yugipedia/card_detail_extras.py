"""Helpers for card detail API (errata, tips)."""

from __future__ import annotations

import json
from urllib.parse import quote

from ygo_app.models import Card
from ygo_app.schemas import CardErrataVersionOut, CardTipsSectionOut

YUGIPEDIA_BASE = "https://yugipedia.com"
ERRATA_UI_LANGUAGE = "English"


def errata_source_url(card_name: str) -> str:
    page = f"Card_Errata:{card_name.replace(' ', '_')}"
    return f"{YUGIPEDIA_BASE}/wiki/{quote(page, safe=':')}"


def card_errata_for_api(card: Card) -> list[CardErrataVersionOut]:
    versions = sorted(
        [v for v in card.errata_versions if v.language == ERRATA_UI_LANGUAGE],
        key=lambda v: v.version_index,
    )
    if not versions and card.errata_versions:
        versions = sorted(card.errata_versions, key=lambda v: (v.language, v.version_index))
    source = errata_source_url(card.name)
    return [
        CardErrataVersionOut(
            version_label=v.version_label,
            lore_text=v.lore_text,
            lore_html=v.lore_html,
            set_code=v.set_code,
            set_name=v.set_name,
            release_date=v.release_date,
            source_url=source,
        )
        for v in versions
    ]


def card_tips_for_api(card: Card) -> list[CardTipsSectionOut]:
    raw = card.tips
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    sections: list[CardTipsSectionOut] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        fmt = str(item.get("format") or "Tips")
        tips = item.get("tips") or []
        if isinstance(tips, list):
            sections.append(
                CardTipsSectionOut(
                    format=fmt,
                    tips=[str(t) for t in tips if str(t).strip()],
                )
            )
    return sections
