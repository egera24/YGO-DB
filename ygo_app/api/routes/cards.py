from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ygo_app.auth import get_current_user, get_optional_user
from ygo_app.config import SEARCH_DEFAULT_LIMIT, SEARCH_MAX_LIMIT
from ygo_app.database import get_db
from ygo_app.models import Card, Printing, User
from ygo_app.schemas import CardDetail, CardSearchPage, CardSummary, PrintingOut, TagMutate
from ygo_app.services import (
    add_user_tag,
    card_summaries_batch,
    card_to_summary,
    get_card_detail,
    get_user_tags,
    remove_user_tag,
    search_cards,
    toggle_favorite,
)
from ygo_app.utils import rarity_display

router = APIRouter(prefix="/cards", tags=["cards"])


@router.get("/search", response_model=CardSearchPage)
def search(
    q: str | None = None,
    type: str | None = Query(None, alias="type"),
    frame_type: str | None = None,
    attribute: str | None = None,
    race: str | None = None,
    archetype: str | None = None,
    set_code: str | None = None,
    owned_only: bool = False,
    favorites_only: bool = False,
    tag: str | None = None,
    limit: int = Query(None, le=SEARCH_MAX_LIMIT),
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    effective_limit = limit if limit is not None else SEARCH_DEFAULT_LIMIT
    cards, total = search_cards(
        db,
        q=q,
        card_type=type,
        frame_type=frame_type,
        attribute=attribute,
        race=race,
        archetype=archetype,
        set_code=set_code,
        owned_only=owned_only,
        favorites_only=favorites_only,
        tag=tag,
        user_id=user.id if user else None,
        limit=effective_limit,
        offset=offset,
    )
    results = []
    extras = card_summaries_batch(db, cards, user.id if user else None)
    for card in cards:
        extra = extras.get(
            card.id, {"owned": False, "owned_quantity": 0, "is_favorite": False}
        )
        results.append(
            CardSummary(
                id=card.id,
                name=card.name,
                type=card.type,
                frame_type=card.frame_type,
                atk=card.atk,
                def_=card.def_,
                level=card.level,
                race=card.race,
                attribute=card.attribute,
                archetype=card.archetype,
                image_url_small=card.image_url_small,
                is_favorite=extra["is_favorite"],
                owned=extra["owned"],
                owned_quantity=extra["owned_quantity"],
            )
        )
    return CardSearchPage(
        items=results, total=total, limit=effective_limit, offset=offset
    )


@router.get("/by-set-code/{set_code}", response_model=CardDetail)
def by_set_code(
    set_code: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    printing = db.execute(
        select(Printing).where(Printing.set_code == set_code).limit(1)
    ).scalar_one_or_none()
    if not printing:
        raise HTTPException(404, f"No printing found for set code {set_code}")
    return _build_card_detail(db, printing.card_id, user)


@router.get("/{card_id}", response_model=CardDetail)
def get_card(
    card_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    return _build_card_detail(db, card_id, user)


def _build_card_detail(db: Session, card_id: int, user: User | None) -> CardDetail:
    card = get_card_detail(db, card_id, user.id if user else None)
    if not card:
        raise HTTPException(404, "Card not found")

    extra = card_to_summary(db, card, user.id if user else None)
    printings = sorted(card.printings, key=lambda p: p.set_code)
    tags = getattr(card, "_user_tags", get_user_tags(db, user.id if user else None, card_id))

    return CardDetail(
        id=card.id,
        name=card.name,
        type=card.type,
        human_readable_type=card.human_readable_type,
        frame_type=card.frame_type,
        desc=card.desc,
        atk=card.atk,
        def_=card.def_,
        level=card.level,
        race=card.race,
        attribute=card.attribute,
        archetype=card.archetype,
        linkval=card.linkval,
        scale=card.scale,
        ygoprodeck_url=card.ygoprodeck_url,
        image_url=card.image_url,
        image_url_small=card.image_url_small,
        is_favorite=getattr(card, "_is_favorite", extra["is_favorite"]),
        owned=extra["owned"],
        owned_quantity=extra["owned_quantity"],
        printings=[
            PrintingOut(
                id=p.id,
                set_name=p.set_name,
                set_code=p.set_code,
                set_rarity=p.set_rarity,
                set_rarity_code=p.set_rarity_code,
                set_price=p.set_price,
                owned_quantity=getattr(p, "owned_quantity", 0),
            )
            for p in printings
        ],
        tags=tags,
    )


@router.post("/{card_id}/favorite")
def toggle_favorite_route(
    card_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    card = db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    is_fav = toggle_favorite(db, user.id, card_id)
    return {"id": card_id, "is_favorite": is_fav}


@router.get("/{card_id}/printings", response_model=list[PrintingOut])
def list_printings(
    card_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    card = get_card_detail(db, card_id, user.id if user else None)
    if not card:
        raise HTTPException(404, "Card not found")
    return [
        PrintingOut(
            id=p.id,
            set_name=p.set_name,
            set_code=p.set_code,
            set_rarity=p.set_rarity,
            set_rarity_code=p.set_rarity_code,
            set_price=p.set_price,
            owned_quantity=getattr(p, "owned_quantity", 0),
        )
        for p in sorted(card.printings, key=lambda x: x.set_code)
    ]


@router.post("/{card_id}/tags")
def add_tag(
    card_id: int,
    body: TagMutate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    card = db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    tag = body.tag.strip()
    if not tag:
        raise HTTPException(400, "Tag cannot be empty")
    tags = add_user_tag(db, user.id, card_id, tag)
    return {"card_id": card_id, "tags": tags}


@router.delete("/{card_id}/tags/{tag}")
def remove_tag(
    card_id: int,
    tag: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    remove_user_tag(db, user.id, card_id, tag)
    return {"ok": True}
