from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
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
    DeckSave,
    DeckUpdate,
    DeckValidationOut,
    ValidationIssueOut,
)
from ygo_app.services import (
    apply_deck_save,
    build_deck_out,
    clear_deck_preview_if_removed,
    compute_deck_preview_cards,
    deck_counts,
    enrich_cards_for_format,
    list_decks_enriched,
    update_deck,
    validate_deck_for_api,
    _deck_card_entries_for_decks,
)

router = APIRouter(prefix="/decks", tags=["decks"])


def _deck_out_from_base(base: dict) -> DeckOut:
    previews = [DeckPreviewCard(**p) for p in base.get("preview_cards", [])]
    payload = {k: v for k, v in base.items() if k != "preview_cards"}
    return DeckOut(**payload, preview_cards=previews)


def _deck_card_out(dc: DeckCard, *, format_extras: dict | None = None) -> DeckCardOut:
    extras = format_extras or {}
    return DeckCardOut(
        card_id=dc.card_id,
        name=dc.card.name,
        type=dc.card.type,
        image_url_small=dc.card.image_url_small,
        image_url=dc.card.image_url,
        zone=dc.zone,
        quantity=dc.quantity,
        sort_order=dc.sort_order,
        banlist_status=extras.get("banlist_status"),
        genesys_points=extras.get("genesys_points"),
    )


def _sorted_deck_cards(deck: Deck) -> list[DeckCard]:
    return sorted(
        deck.cards,
        key=lambda dc: (
            {"main": 0, "extra": 1, "side": 2}.get(dc.zone, 99),
            dc.sort_order,
        ),
    )


def _validation_out(validation: dict | None) -> DeckValidationOut | None:
    if not validation:
        return None
    return DeckValidationOut(**validation)


def _deck_detail_from_deck(deck: Deck, db: Session) -> DeckDetail:
    counts = deck_counts(db, deck.id)
    entries = _deck_card_entries_for_decks(db, [deck.id]).get(deck.id, [])
    previews = compute_deck_preview_cards(deck.preview_card_id, entries)
    validation = validate_deck_for_api(db, deck)
    base = build_deck_out(deck, counts, previews, validation=validation)
    sorted_cards = _sorted_deck_cards(deck)
    card_models = [dc.card for dc in sorted_cards]
    format_extras = enrich_cards_for_format(
        db,
        card_models,
        format_code=deck.format_code,
        banlist_revision_id=deck.banlist_revision_id,
        genesys_point_list_id=deck.genesys_point_list_id,
        for_search=True,
    )
    cards = [
        _deck_card_out(dc, format_extras=format_extras.get(dc.card_id))
        for dc in sorted_cards
    ]
    out = _deck_out_from_base(base)
    return DeckDetail(**out.model_dump(), cards=cards, validation=_validation_out(validation))


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
        format_code=body.format_code,
        banlist_revision_id=body.banlist_revision_id,
        genesys_point_list_id=body.genesys_point_list_id,
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


@router.put("/{deck_id}", response_model=DeckDetail)
def save_deck(
    deck_id: int,
    body: DeckSave,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    deck = _get_user_deck(db, deck_id, user.id)
    if not deck:
        raise HTTPException(404, "Deck not found")
    try:
        apply_deck_save(db, deck, body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return get_deck(deck_id, db, user)


@router.post("/{deck_id}/validate-preview", response_model=DeckValidationOut)
def validate_deck_preview(
    deck_id: int,
    body: DeckSave,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    deck = _get_user_deck(db, deck_id, user.id)
    if not deck:
        raise HTTPException(404, "Deck not found")
    nested = db.begin_nested()
    try:
        apply_deck_save(db, deck, body.model_dump())
        db.flush()
        validation = validate_deck_for_api(db, deck)
    except ValueError as exc:
        nested.rollback()
        raise HTTPException(400, str(exc)) from exc
    nested.rollback()
    db.expire_all()
    out = _validation_out(validation)
    if out is None:
        raise HTTPException(500, "Validation preview failed")
    return out


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
    max_sort = db.execute(
        select(func.coalesce(func.max(DeckCard.sort_order), -1)).where(
            DeckCard.deck_id == deck_id,
            DeckCard.zone == zone,
        )
    ).scalar_one()

    for offset in range(body.quantity):
        db.add(
            DeckCard(
                deck_id=deck_id,
                card_id=body.card_id,
                zone=zone,
                quantity=1,
                sort_order=max_sort + 1 + offset,
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
    rows = list(
        db.execute(
            select(DeckCard)
            .where(
                DeckCard.deck_id == deck_id,
                DeckCard.card_id == card_id,
                DeckCard.zone == zone,
            )
            .order_by(DeckCard.sort_order.asc(), DeckCard.id.asc())
        )
        .scalars()
        .all()
    )
    if not rows and quantity > 0:
        raise HTTPException(404, "Card not in deck")
    if quantity <= 0:
        for row in rows:
            db.delete(row)
        clear_deck_preview_if_removed(db, deck_id, card_id)
    elif quantity < len(rows):
        for row in rows[quantity:]:
            db.delete(row)
    elif quantity > len(rows):
        max_sort = db.execute(
            select(func.coalesce(func.max(DeckCard.sort_order), -1)).where(
                DeckCard.deck_id == deck_id,
                DeckCard.zone == zone,
            )
        ).scalar_one()
        for offset in range(quantity - len(rows)):
            db.add(
                DeckCard(
                    deck_id=deck_id,
                    card_id=card_id,
                    zone=zone,
                    quantity=1,
                    sort_order=max_sort + 1 + offset,
                )
            )
    deck = db.get(Deck, deck_id)
    if deck:
        deck.updated_at = datetime.utcnow()
    db.commit()
    return get_deck(deck_id, db, user)


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
    rows = list(
        db.execute(
            select(DeckCard).where(
                DeckCard.deck_id == deck_id,
                DeckCard.card_id == card_id,
                DeckCard.zone == zone,
            )
        )
        .scalars()
        .all()
    )
    if rows:
        for row in rows:
            db.delete(row)
        clear_deck_preview_if_removed(db, deck_id, card_id)
        deck = db.get(Deck, deck_id)
        if deck:
            deck.updated_at = datetime.utcnow()
        db.commit()
    return {"ok": True}
