"""Public trade subsite API (no authentication)."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ygo_app.config import TURNSTILE_SITE_KEY
from ygo_app.currency import get_eur_huf_rate
from ygo_app.database import get_db
from ygo_app.email import send_trade_order_request
from ygo_app.rate_limit import RateLimitSpec, enforce_rate_limit
from ygo_app.request_client import client_ip
from ygo_app.schemas import (
    PublicConfigOut,
    PublicTradeFiltersOut,
    PublicTradeItemOut,
    PublicTradeListOut,
    PublicTradeSellerOut,
    TradeOrderRequestIn,
    TradeOrderRequestOut,
)
from ygo_app.services import (
    get_user_by_trade_slug,
    list_public_trade_items,
    public_trade_filters,
    validate_and_build_trade_order,
)
from ygo_app.trade_export import export_public_trade_xlsx
from ygo_app.turnstile import turnstile_required, verify_turnstile_token

router = APIRouter(prefix="/public", tags=["public"])
logger = logging.getLogger(__name__)

TRADE_ORDER_IP_LIMIT = RateLimitSpec(max_count=5, window_seconds=3600)
TRADE_EXPORT_IP_LIMIT = RateLimitSpec(max_count=30, window_seconds=3600)


@router.get("/config", response_model=PublicConfigOut)
def public_config():
    rate = get_eur_huf_rate()
    return PublicConfigOut(
        turnstile_site_key=TURNSTILE_SITE_KEY,
        eur_huf_rate=rate.rate,
        eur_huf_rate_source=rate.source,
        eur_huf_rate_as_of=rate.as_of,
    )


def _owner_or_404(db: Session, slug: str):
    owner = get_user_by_trade_slug(db, slug)
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trade list not found")
    return owner


@router.get("/trade/{slug}", response_model=PublicTradeListOut)
def get_public_trade_list(
    slug: str,
    q: str | None = None,
    set_code: str | None = None,
    rarity: str | None = None,
    sort: str = Query(
        "set_code",
        pattern="^(set_code|card_name|trade_quantity|sell_price|condition)$",
    ),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    owner = _owner_or_404(db, slug)
    items, total = list_public_trade_items(
        db,
        user_id=owner.id,
        q=q,
        set_code=set_code,
        rarity=rarity,
        sort=sort,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )
    return PublicTradeListOut(
        seller=PublicTradeSellerOut(display_name=owner.trade_display_name),
        items=[PublicTradeItemOut(**item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/trade/{slug}/filters", response_model=PublicTradeFiltersOut)
def get_public_trade_filters(slug: str, db: Session = Depends(get_db)):
    owner = _owner_or_404(db, slug)
    return PublicTradeFiltersOut(**public_trade_filters(db, user_id=owner.id))


@router.get("/trade/{slug}/export-xlsx")
def export_public_trade_list_xlsx(
    slug: str,
    request: Request,
    q: str | None = None,
    set_code: str | None = None,
    rarity: str | None = None,
    sort: str = Query(
        "set_code",
        pattern="^(set_code|card_name|trade_quantity|sell_price|condition)$",
    ),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    owner = _owner_or_404(db, slug)
    ip = client_ip(request)
    enforce_rate_limit(db, f"trade-export:ip:{ip}", TRADE_EXPORT_IP_LIMIT)
    db.commit()

    content, media_type, filename = export_public_trade_xlsx(
        db,
        user_id=owner.id,
        slug=slug,
        q=q,
        set_code=set_code,
        rarity=rarity,
        sort=sort,
        sort_dir=sort_dir,
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/trade/{slug}/order-request", response_model=TradeOrderRequestOut)
def submit_trade_order_request(
    slug: str,
    body: TradeOrderRequestIn,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    owner = _owner_or_404(db, slug)
    ip = client_ip(request)
    enforce_rate_limit(db, f"trade-order:ip:{ip}", TRADE_ORDER_IP_LIMIT)
    db.commit()

    if turnstile_required() and not verify_turnstile_token(body.turnstile_token, ip):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Captcha verification failed")

    try:
        lines = validate_and_build_trade_order(
            db,
            owner.id,
            [line.model_dump() for line in body.lines],
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    buyer_contact = {
        "name": body.name,
        "email": str(body.email) if body.email else None,
        "phone": body.phone,
        "address": body.address,
    }
    submitted_at = datetime.utcnow()

    background_tasks.add_task(
        send_trade_order_request,
        owner_email=owner.email,
        seller_display_name=owner.trade_display_name,
        buyer_contact=buyer_contact,
        lines=lines,
        submitted_at=submitted_at,
    )

    logger.info(
        "Trade order queued for slug=%s line_count=%d",
        slug,
        len(lines),
    )
    return TradeOrderRequestOut(message="Order request sent.")
