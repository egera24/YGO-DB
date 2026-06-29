import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ygo_app.auth import get_current_user
from ygo_app.card_filters import card_response_extras
from ygo_app.config import SEARCH_DEFAULT_LIMIT, SEARCH_MAX_LIMIT
from ygo_app.database import get_db
from ygo_app.models import Card, Printing, User
from ygo_app.schemas import CardDetail, CardSearchPage, CardSummary, PrintingOut, TagMutate
from ygo_app.services import (
    add_user_tag,
    card_summaries_batch,
    get_card_detail,
    list_user_tags,
    remove_user_tag,
    search_cards,
    summoning_condition_suggestions,
    toggle_favorite,
)
from ygo_app.yugipedia.card_detail_extras import card_errata_for_api, card_tips_for_api
from ygo_app.yugipedia.images import resolve_display_image_url_small

router = APIRouter(prefix="/cards", tags=["cards"])

_DEBUG_LOG_PATH = Path(__file__).resolve().parents[3] / "debug-906c06.log"


def _agent_debug_log(location: str, message: str, data: dict, hypothesis_id: str) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "906c06",
            "runId": "pre-fix",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")
    except OSError:
        pass
    # #endregion


def _printing_out(p: Printing) -> PrintingOut:
    return PrintingOut(
        id=p.id,
        set_name=p.set_name,
        set_code=p.set_code,
        set_rarity=p.set_rarity,
        set_rarity_code=p.set_rarity_code,
        set_price=p.set_price,
        owned_quantity=getattr(p, "owned_quantity", 0),
        trade_quantity=getattr(p, "trade_quantity", 0),
        collection_item_id=getattr(p, "collection_item_id", None),
        low_price=getattr(p, "low_price", None),
        avg_price=getattr(p, "avg_price", None),
        trend_price=getattr(p, "trend_price", None),
        price_currency=getattr(p, "price_currency", None),
        prices_updated_at=getattr(p, "prices_updated_at", None),
    )


def _card_summary(card: Card, extra: dict) -> CardSummary:
    yugi = card_response_extras(card)
    return CardSummary(
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
        category=card.category,
        types=yugi["types"],
        mechanic=card.mechanic,
        rank=card.rank,
        link_rating=yugi["link_rating"],
        pendulum_scale=yugi["pendulum_scale"],
        link_markers=yugi["link_markers"],
        summoning_condition=card.summoning_condition,
        image_url_small=resolve_display_image_url_small(
            card.image_url_small, card.image_url
        ),
        is_favorite=extra["is_favorite"],
        owned=extra["owned"],
        owned_quantity=extra["owned_quantity"],
        trade_quantity=extra.get("trade_quantity", 0),
    )


@router.get("/search", response_model=CardSearchPage)
def search(
    q: str | None = None,
    type: str | None = Query(None, alias="type"),
    archetype: str | None = None,
    category: str | None = None,
    types: str | None = None,
    mechanic: str | None = None,
    attribute: str | None = None,
    summoning_condition: str | None = None,
    link_markers: str | None = None,
    atk_min: int | None = None,
    atk_max: int | None = None,
    def_min: int | None = None,
    def_max: int | None = None,
    level_min: int | None = None,
    level_max: int | None = None,
    rank_min: int | None = None,
    rank_max: int | None = None,
    link_rating_min: int | None = None,
    link_rating_max: int | None = None,
    pendulum_scale_min: int | None = None,
    pendulum_scale_max: int | None = None,
    set_code: str | None = None,
    owned_only: bool = False,
    favorites_only: bool = False,
    tag: str | None = None,
    limit: int = Query(None, le=SEARCH_MAX_LIMIT),
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    effective_limit = limit if limit is not None else SEARCH_DEFAULT_LIMIT
    cards, total = search_cards(
        db,
        q=q,
        card_type=type,
        archetype=archetype,
        category=category,
        types=types,
        mechanic=mechanic,
        attribute=attribute,
        summoning_condition=summoning_condition,
        link_markers=link_markers,
        atk_min=atk_min,
        atk_max=atk_max,
        def_min=def_min,
        def_max=def_max,
        level_min=level_min,
        level_max=level_max,
        rank_min=rank_min,
        rank_max=rank_max,
        link_rating_min=link_rating_min,
        link_rating_max=link_rating_max,
        pendulum_scale_min=pendulum_scale_min,
        pendulum_scale_max=pendulum_scale_max,
        set_code=set_code,
        owned_only=owned_only,
        favorites_only=favorites_only,
        tag=tag,
        user_id=user.id,
        limit=effective_limit,
        offset=offset,
    )
    extras = card_summaries_batch(db, cards, user.id)
    results = [_card_summary(card, extras.get(card.id, {})) for card in cards]
    return CardSearchPage(
        items=results, total=total, limit=effective_limit, offset=offset
    )


@router.get("/summoning-suggestions")
def summoning_suggestions(
    q: str = "",
    limit: int = Query(20, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"suggestions": summoning_condition_suggestions(db, q=q, limit=limit)}


@router.get("/tags")
def user_tags(
    q: str = "",
    limit: int = Query(200, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"tags": list_user_tags(db, user.id, q=q or None, limit=limit)}


@router.get("/by-set-code/{set_code}", response_model=CardDetail)
def by_set_code(
    set_code: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
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
    user: User = Depends(get_current_user),
):
    return _build_card_detail(db, card_id, user)


def _summary_extra_from_card(card: Card) -> dict:
    owned_qty = sum(getattr(p, "owned_quantity", 0) for p in card.printings)
    trade_qty = sum(getattr(p, "trade_quantity", 0) for p in card.printings)
    return {
        "is_favorite": getattr(card, "_is_favorite", False),
        "owned": owned_qty > 0,
        "owned_quantity": owned_qty,
        "trade_quantity": trade_qty,
    }


def _build_card_detail(db: Session, card_id: int, user: User) -> CardDetail:
    card = get_card_detail(db, card_id, user.id)
    if not card:
        raise HTTPException(404, "Card not found")

    extra = _summary_extra_from_card(card)
    printings = sorted(card.printings, key=lambda p: p.set_code)
    tags = getattr(card, "_user_tags", [])
    priced_count = sum(
        1
        for p in printings
        if any(getattr(p, field, None) is not None for field in ("low_price", "avg_price", "trend_price"))
    )
    _agent_debug_log(
        "cards.py:_build_card_detail",
        "built card detail",
        {
            "card_id": card_id,
            "printings_count": len(printings),
            "priced_printings_count": priced_count,
            "user_id": user.id,
        },
        "B",
    )

    summary = _card_summary(card, extra)
    return CardDetail(
        **summary.model_dump(),
        human_readable_type=card.human_readable_type,
        desc=card.desc,
        linkval=card.linkval,
        scale=card.scale,
        ygoprodeck_url=card.ygoprodeck_url,
        image_url=card.image_url,
        printings=[_printing_out(p) for p in printings],
        tags=tags,
        has_errata=bool(card.has_errata),
        last_erratum_date=card.last_erratum_date,
        errata=card_errata_for_api(card),
        tips=card_tips_for_api(card),
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
    user: User = Depends(get_current_user),
):
    card = get_card_detail(db, card_id, user.id)
    if not card:
        raise HTTPException(404, "Card not found")
    return [_printing_out(p) for p in sorted(card.printings, key=lambda x: x.set_code)]


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
