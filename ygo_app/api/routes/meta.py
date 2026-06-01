from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ygo_app.auth import get_current_user, get_optional_user
from ygo_app.config import IS_PRODUCTION
from ygo_app.database import get_db
from ygo_app.models import Card, CollectionItem, Deck, Printing, User

router = APIRouter(tags=["meta"])


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/status")
def status(
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    try:
        card_count = db.execute(select(func.count()).select_from(Card)).scalar() or 0
    except Exception:
        card_count = 0

    collection_count = 0
    deck_count = 0
    if user and card_count:
        collection_count = (
            db.execute(
                select(func.count())
                .select_from(CollectionItem)
                .where(CollectionItem.user_id == user.id)
            ).scalar()
            or 0
        )
        deck_count = (
            db.execute(
                select(func.count()).select_from(Deck).where(Deck.user_id == user.id)
            ).scalar()
            or 0
        )

    payload = {
        "cards": card_count,
        "printings": db.execute(select(func.count()).select_from(Printing)).scalar() or 0
        if card_count
        else 0,
        "collection_items": collection_count,
        "decks": deck_count,
        "ready": card_count > 0,
        "authenticated": user is not None,
    }
    if not IS_PRODUCTION:
        from ygo_app.config import DB_PATH

        payload["database_exists"] = DB_PATH.exists() if DB_PATH else True
    return payload


@router.get("/filters")
def filters(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    folders = (
        db.execute(
            select(CollectionItem.folder_name)
            .where(
                CollectionItem.user_id == user.id,
                CollectionItem.folder_name.isnot(None),
            )
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
        text(
            "SELECT DISTINCT frame_type FROM cards WHERE frame_type IS NOT NULL ORDER BY frame_type"
        )
    ).scalars().all()
    return {
        "folders": folders,
        "attributes": attributes,
        "races": races,
        "frame_types": frames,
    }
