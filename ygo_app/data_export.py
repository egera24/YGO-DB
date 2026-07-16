"""Build a GDPR-oriented personal data export for an account holder."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ygo_app.models import (
    CollectionFolder,
    CollectionItem,
    Deck,
    OAuthIdentity,
    SearchPreset,
    User,
    UserCardTag,
    UserFavorite,
)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + ("Z" if value.tzinfo is None else "")


def build_user_data_export(session: Session, user: User) -> dict:
    oauth_rows = session.scalars(
        select(OAuthIdentity).where(OAuthIdentity.user_id == user.id)
    ).all()
    folders = session.scalars(
        select(CollectionFolder)
        .where(CollectionFolder.user_id == user.id)
        .order_by(CollectionFolder.sort_order, CollectionFolder.id)
    ).all()
    items = session.scalars(
        select(CollectionItem)
        .where(CollectionItem.user_id == user.id)
        .options(selectinload(CollectionItem.folder_allocations))
        .order_by(CollectionItem.id)
    ).all()
    decks = session.scalars(
        select(Deck)
        .where(Deck.user_id == user.id)
        .options(selectinload(Deck.cards))
        .order_by(Deck.id)
    ).all()
    favorites = session.scalars(
        select(UserFavorite).where(UserFavorite.user_id == user.id).order_by(UserFavorite.id)
    ).all()
    tags = session.scalars(
        select(UserCardTag).where(UserCardTag.user_id == user.id).order_by(UserCardTag.id)
    ).all()
    presets = session.scalars(
        select(SearchPreset)
        .where(SearchPreset.user_id == user.id)
        .order_by(SearchPreset.id)
    ).all()

    preset_payload = []
    for preset in presets:
        try:
            params = json.loads(preset.params)
        except (TypeError, ValueError, json.JSONDecodeError):
            params = preset.params
        preset_payload.append(
            {
                "id": preset.id,
                "name": preset.name,
                "params": params,
                "created_at": _iso(preset.created_at),
                "updated_at": _iso(preset.updated_at),
            }
        )

    return {
        "exported_at": _iso(datetime.utcnow()),
        "profile": {
            "email": user.email,
            "created_at": _iso(user.created_at),
            "email_verified_at": _iso(user.email_verified_at),
            "trade_share_slug": user.trade_share_slug,
            "trade_display_name": user.trade_display_name,
        },
        "oauth_identities": [
            {
                "provider": row.provider,
                "provider_email": row.provider_email,
                "created_at": _iso(row.created_at),
            }
            for row in oauth_rows
        ],
        "folders": [
            {
                "id": folder.id,
                "name": folder.name,
                "sort_order": folder.sort_order,
                "created_at": _iso(folder.created_at),
            }
            for folder in folders
        ],
        "collection": [
            {
                "id": item.id,
                "set_code": item.set_code,
                "rarity_code": item.rarity_code,
                "card_name": item.card_name,
                "expansion_code": item.expansion_code,
                "set_name": item.set_name,
                "quantity": item.quantity,
                "trade_quantity": item.trade_quantity,
                "condition": item.condition,
                "edition": item.edition,
                "language": item.language,
                "price_bought": item.price_bought,
                "date_bought": item.date_bought,
                "sell_price": item.sell_price,
                "printing_id": item.printing_id,
                "notes": item.notes,
                "folder_allocations": [
                    {
                        "folder_id": alloc.folder_id,
                        "quantity": alloc.quantity,
                    }
                    for alloc in item.folder_allocations
                ],
            }
            for item in items
        ],
        "decks": [
            {
                "id": deck.id,
                "name": deck.name,
                "description": deck.description,
                "format_code": deck.format_code,
                "banlist_revision_id": deck.banlist_revision_id,
                "genesys_point_list_id": deck.genesys_point_list_id,
                "preview_card_id": deck.preview_card_id,
                "created_at": _iso(deck.created_at),
                "updated_at": _iso(deck.updated_at),
                "cards": [
                    {
                        "card_id": entry.card_id,
                        "zone": entry.zone,
                        "quantity": entry.quantity,
                        "sort_order": entry.sort_order,
                    }
                    for entry in deck.cards
                ],
            }
            for deck in decks
        ],
        "favorites": [{"card_id": fav.card_id} for fav in favorites],
        "card_tags": [
            {"card_id": tag.card_id, "tag": tag.tag} for tag in tags
        ],
        "search_presets": preset_payload,
    }
