"""Shared test helpers for Cardmarket catalog tests."""

from __future__ import annotations

from datetime import datetime

from ygo_app.models import RarityPriceRank

RARITY_ROWS = [
    (1, "Common", "C"),
    (2, "Normal Rare", "N"),
    (10, "Super Rare", "SR"),
    (18, "Ultra Rare", "UR"),
    (23, "Secret Rare", "ScR"),
]


def seed_rarity_price_ranks(session) -> None:
    for sort_order, name, rarity_code in RARITY_ROWS:
        session.add(
            RarityPriceRank(
                sort_order=sort_order,
                name=name,
                rarity_code=rarity_code,
            )
        )
    session.commit()


def make_current_price(**kwargs):
    defaults = {
        "valid_from": datetime.utcnow(),
        "valid_to": None,
        "is_current": True,
        "currency": "EUR",
    }
    defaults.update(kwargs)
    return defaults
