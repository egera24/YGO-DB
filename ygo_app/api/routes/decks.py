from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ygo_app.auth import get_current_user
from ygo_app.database import get_db
from ygo_app.models import Card, Deck, DeckCard, User
from ygo_app.schemas import DeckCardMutate, DeckCardOut, DeckCreate, DeckDetail, DeckOut
from ygo_app.services import deck_counts

router = APIRouter(prefix="/decks", tags=["decks"])


def _deck_out(deck: Deck, counts: dict[str, int]) -> DeckOut:
    return DeckOut(
        id=deck.id,
        name=deck.name,
        description=deck.description,
        created_at=deck.created_at,
        updated_at=deck.updated_at,
        main_count=counts.get("main", 0),
        extra_count=counts.get("extra", 0),
        side_count=counts.get("side", 0),
    )


def _get_user_deck(db: Session, deck_id: int, user_id: int) -> Deck | None:
    deck = db.get(Deck, deck_id)
    if not deck or deck.user_id != user_id:
        return None
    return deck


@router.get("", response_model=list[DeckOut])
def list_decks(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    decks = (
        db.execute(
            select(Deck)
            .where(Deck.user_id == user.id)
            .order_by(Deck.updated_at.desc())
        )
        .scalars()
        .all()
    )
    return [_deck_out(d, deck_counts(db, d.id)) for d in decks]


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
    return _deck_out(deck, {"main": 0, "extra": 0, "side": 0})


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
    counts = deck_counts(db, deck_id)
    cards = [
        DeckCardOut(
            card_id=dc.card_id,
            name=dc.card.name,
            type=dc.card.type,
            image_url_small=dc.card.image_url_small,
            zone=dc.zone,
            quantity=dc.quantity,
        )
        for dc in deck.cards
    ]
    base = _deck_out(deck, counts)
    return DeckDetail(**base.model_dump(), cards=cards)


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
        deck = db.get(Deck, deck_id)
        if deck:
            deck.updated_at = datetime.utcnow()
        db.commit()
    return {"ok": True}
