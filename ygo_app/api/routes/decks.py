from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ygo_app.auth import get_current_user
from ygo_app.database import get_db
from ygo_app.models import Card, Deck, DeckCard, User
from ygo_app.schemas import (
    DeckCardMutate,
    DeckCardOut,
    DeckCreate,
    DeckDetail,
    DeckOut,
    DeckPreviewCard,
    DeckUpdate,
)
from ygo_app.services import (
    build_deck_out,
    clear_deck_preview_if_removed,
    compute_deck_preview_cards,
    deck_counts,
    list_decks_enriched,
    update_deck,
    _deck_card_entries_for_decks,
)

router = APIRouter(prefix="/decks", tags=["decks"])


def _deck_out_from_base(base: dict) -> DeckOut:
    previews = [DeckPreviewCard(**p) for p in base.get("preview_cards", [])]
    payload = {k: v for k, v in base.items() if k != "preview_cards"}
    return DeckOut(**payload, preview_cards=previews)


def _deck_card_out(dc: DeckCard) -> DeckCardOut:
    return DeckCardOut(
        card_id=dc.card_id,
        name=dc.card.name,
        type=dc.card.type,
        image_url_small=dc.card.image_url_small,
        image_url=dc.card.image_url,
        zone=dc.zone,
        quantity=dc.quantity,
    )


def _deck_detail_from_deck(deck: Deck, db: Session) -> DeckDetail:
    counts = deck_counts(db, deck.id)
    entries = _deck_card_entries_for_decks(db, [deck.id]).get(deck.id, [])
    previews = compute_deck_preview_cards(deck.preview_card_id, entries)
    base = build_deck_out(deck, counts, previews)
    cards = [_deck_card_out(dc) for dc in deck.cards]
    out = _deck_out_from_base(base)
    return DeckDetail(**out.model_dump(), cards=cards)


def _get_user_deck(db: Session, deck_id: int, user_id: int) -> Deck | None:
    deck = db.get(Deck, deck_id)
    if not deck or deck.user_id != user_id:
        return None
    return deck


@router.get("", response_model=list[DeckOut])
def list_decks(
    q: str | None = Query(None),
    sort: str = Query("updated_at", pattern="^(name|created_at|updated_at)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = list_decks_enriched(db, user.id, q=q, sort=sort)
    return [_deck_out_from_base(row) for row in rows]


@router.post("", response_model=DeckOut)
def create_deck(
    body: DeckCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    deck = Deck(
        user_id=user.id,
        name=body.name.strip(),
        description=body.description,
    )
    db.add(deck)
    db.commit()
    db.refresh(deck)
    counts = {"main": 0, "extra": 0, "side": 0}
    base = build_deck_out(deck, counts, [])
    return _deck_out_from_base(base)


@router.get("/{deck_id}", response_model=DeckDetail)
def get_deck(
    deck_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    deck = db.get(
        Deck,
        deck_id,
        options=[joinedload(Deck.cards).joinedload(DeckCard.card)],
    )
    if not deck or deck.user_id != user.id:
        raise HTTPException(404, "Deck not found")
    return _deck_detail_from_deck(deck, db)


@router.patch("/{deck_id}", response_model=DeckOut)
def patch_deck(
    deck_id: int,
    body: DeckUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    deck = _get_user_deck(db, deck_id, user.id)
    if not deck:
        raise HTTPException(404, "Deck not found")
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        counts = deck_counts(db, deck_id)
        entries = _deck_card_entries_for_decks(db, [deck_id]).get(deck_id, [])
        previews = compute_deck_preview_cards(deck.preview_card_id, entries)
        base = build_deck_out(deck, counts, previews)
        return _deck_out_from_base(base)
    try:
        update_deck(db, deck, updates)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    counts = deck_counts(db, deck_id)
    entries = _deck_card_entries_for_decks(db, [deck_id]).get(deck_id, [])
    previews = compute_deck_preview_cards(deck.preview_card_id, entries)
    base = build_deck_out(deck, counts, previews)
    return _deck_out_from_base(base)


@router.delete("/{deck_id}")
def delete_deck(
    deck_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    deck = _get_user_deck(db, deck_id, user.id)
    if not deck:
        raise HTTPException(404, "Deck not found")
    db.delete(deck)
    db.commit()
    return {"ok": True}


@router.post("/{deck_id}/cards", response_model=DeckDetail)
def add_card_to_deck(
    deck_id: int,
    body: DeckCardMutate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    deck = _get_user_deck(db, deck_id, user.id)
    if not deck:
        raise HTTPException(404, "Deck not found")
    card = db.get(Card, body.card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    zone = body.zone if body.zone in ("main", "extra", "side") else "main"
    existing = db.execute(
        select(DeckCard).where(
            DeckCard.deck_id == deck_id,
            DeckCard.card_id == body.card_id,
            DeckCard.zone == zone,
        )
    ).scalar_one_or_none()

    if existing:
        existing.quantity += body.quantity
    else:
        db.add(
            DeckCard(
                deck_id=deck_id,
                card_id=body.card_id,
                zone=zone,
                quantity=body.quantity,
            )
        )
    deck.updated_at = datetime.utcnow()
    db.commit()
    return get_deck(deck_id, db, user)


@router.patch("/{deck_id}/cards/{card_id}")
def update_deck_card(
    deck_id: int,
    card_id: int,
    quantity: int = Query(..., ge=0),
    zone: str = Query("main"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _get_user_deck(db, deck_id, user.id):
        raise HTTPException(404, "Deck not found")
    row = db.execute(
        select(DeckCard).where(
            DeckCard.deck_id == deck_id,
            DeckCard.card_id == card_id,
            DeckCard.zone == zone,
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Card not in deck")
    if quantity <= 0:
        db.delete(row)
        clear_deck_preview_if_removed(db, deck_id, card_id)
    else:
        row.quantity = quantity
    deck = db.get(Deck, deck_id)
    if deck:
        deck.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.delete("/{deck_id}/cards/{card_id}")
def remove_from_deck(
    deck_id: int,
    card_id: int,
    zone: str = "main",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _get_user_deck(db, deck_id, user.id):
        raise HTTPException(404, "Deck not found")
    row = db.execute(
        select(DeckCard).where(
            DeckCard.deck_id == deck_id,
            DeckCard.card_id == card_id,
            DeckCard.zone == zone,
        )
    ).scalar_one_or_none()
    if row:
        db.delete(row)
        clear_deck_preview_if_removed(db, deck_id, card_id)
        deck = db.get(Deck, deck_id)
        if deck:
            deck.updated_at = datetime.utcnow()
        db.commit()
    return {"ok": True}
