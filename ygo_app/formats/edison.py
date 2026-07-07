"""Edison-era errata text selection."""

from __future__ import annotations

from datetime import date

from ygo_app.models import Card

EDISON_ERRATA_CUTOFF = date(2010, 3, 31)


def errata_text_as_of(card: Card, as_of: date = EDISON_ERRATA_CUTOFF) -> str | None:
    versions = [
        version
        for version in (card.errata_versions or [])
        if version.release_date and version.release_date <= as_of and version.lore_text
    ]
    if versions:
        versions.sort(key=lambda v: (v.release_date, v.version_index))
        return versions[-1].lore_text
    return card.desc
