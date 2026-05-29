from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ygo_app.config import DB_PATH
from ygo_app.database import get_db
from ygo_app.models import Card, CollectionItem, Deck, Printing

router = APIRouter(tags=["meta"])


@router.get("/status")
def status(db: Session = Depends(get_db)):
    try:
        card_count = db.execute(select(func.count()).select_from(Card)).scalar() or 0
    except Exception:
        card_count = 0

    return {
        "database": str(DB_PATH),
        "database_exists": DB_PATH.exists(),
        "cards": card_count,
        "printings": db.execute(select(func.count()).select_from(Printing)).scalar() or 0
        if card_count
        else 0,
        "collection_items": db.execute(select(func.count()).select_from(CollectionItem)).scalar()
        or 0
        if card_count
        else 0,
        "decks": db.execute(select(func.count()).select_from(Deck)).scalar() or 0
        if card_count
        else 0,
        "ready": card_count > 0,
    }


@router.get("/filters")
def filters(db: Session = Depends(get_db)):
    folders = (
        db.execute(
            select(CollectionItem.folder_name)
            .where(CollectionItem.folder_name.isnot(None))
            .distinct()
            .order_by(CollectionItem.folder_name)
        )
        .scalars()
        .all()
    )
    attributes = db.execute(
        text("SELECT DISTINCT attribute FROM cards WHERE attribute IS NOT NULL ORDER BY attribute")
    ).scalars().all()
    races = db.execute(
        text("SELECT DISTINCT race FROM cards WHERE race IS NOT NULL ORDER BY race")
    ).scalars().all()
    frames = db.execute(
        text("SELECT DISTINCT frame_type FROM cards WHERE frame_type IS NOT NULL ORDER BY frame_type")
    ).scalars().all()
    return {
        "folders": folders,
        "attributes": attributes,
        "races": races,
        "frame_types": frames,
    }
