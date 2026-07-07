from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ygo_app.auth import get_current_user
from ygo_app.database import get_db
from ygo_app.formats.base import DECK_ZONE_TOOLTIPS
from ygo_app.models import BanlistRevision, Format, GenesysPointList, User
from ygo_app.schemas import BanlistRevisionOut, FormatOut, GenesysPointListOut

router = APIRouter(prefix="/formats", tags=["formats"])


@router.get("", response_model=list[FormatOut])
def list_formats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.execute(select(Format).order_by(Format.sort_order)).scalars().all()
    return [
        FormatOut(
            code=row.code,
            name=row.name,
            description=row.description,
            uses_banlist=row.uses_banlist,
            uses_point_list=row.uses_point_list,
            zone_tooltips=DECK_ZONE_TOOLTIPS,
        )
        for row in rows
    ]


@router.get("/{format_code}/banlists", response_model=list[BanlistRevisionOut])
def list_banlists(
    format_code: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    fmt = db.get(Format, format_code)
    if not fmt:
        raise HTTPException(404, "Format not found")
    if not fmt.uses_banlist:
        return []
    rows = db.execute(
        select(BanlistRevision).order_by(
            desc(BanlistRevision.effective_from), desc(BanlistRevision.id)
        )
    ).scalars().all()
    return [
        BanlistRevisionOut(
            id=row.id,
            label=row.label,
            effective_from=row.effective_from,
            source_list_id=row.source_list_id,
            is_current=row.source_list_id == "current",
        )
        for row in rows
    ]


@router.get("/genesys/point-lists", response_model=list[GenesysPointListOut])
def list_genesys_point_lists(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = db.execute(
        select(GenesysPointList).order_by(desc(GenesysPointList.effective_from))
    ).scalars().all()
    return [
        GenesysPointListOut(
            id=row.id,
            label=row.label,
            effective_from=row.effective_from,
        )
        for row in rows
    ]
