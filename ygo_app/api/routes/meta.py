import time

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ygo_app.auth import get_current_user
from ygo_app.card_filters import parse_json_string_list
from ygo_app.config import IS_PRODUCTION
from ygo_app.database import get_db
from ygo_app.models import Card, CollectionItem, Deck, Printing, User

router = APIRouter(tags=["meta"])

FILTER_ARCHETYPE_LIMIT = 500
_FILTERS_CACHE_TTL_SECONDS = 600
_catalog_filters_cache: dict | None = None
_catalog_filters_cached_at: float = 0.0


def invalidate_catalog_filters_cache() -> None:
    """Clear cached catalog filter options (e.g. after catalog import)."""
    global _catalog_filters_cache, _catalog_filters_cached_at
    _catalog_filters_cache = None
    _catalog_filters_cached_at = 0.0


def _column_min_max(db: Session, column) -> dict[str, int] | None:
    row = db.execute(
        select(func.min(column), func.max(column)).where(column.isnot(None))
    ).one()
    lo, hi = row[0], row[1]
    if lo is None or hi is None:
        return None
    return {"min": int(lo), "max": int(hi)}


def _catalog_stat_ranges(db: Session) -> dict[str, dict[str, int] | None]:
    return {
        "level": _column_min_max(db, Card.level),
        "rank": _column_min_max(db, Card.rank),
        "link_rating": _column_min_max(db, Card.link_rating),
        "pendulum_scale": _column_min_max(db, Card.pendulum_scale),
        "atk": _column_min_max(db, Card.atk),
        "def": _column_min_max(db, Card.def_),
    }


def _load_catalog_filters(db: Session) -> dict:
    global _catalog_filters_cache, _catalog_filters_cached_at
    now = time.monotonic()
    if (
        _catalog_filters_cache is not None
        and now - _catalog_filters_cached_at < _FILTERS_CACHE_TTL_SECONDS
    ):
        return _catalog_filters_cache

    categories = db.execute(
        text(
            "SELECT DISTINCT category FROM cards "
            "WHERE category IS NOT NULL ORDER BY category"
        )
    ).scalars().all()
    attributes = db.execute(
        text("SELECT DISTINCT attribute FROM cards WHERE attribute IS NOT NULL ORDER BY attribute")
    ).scalars().all()
    mechanics = db.execute(
        text("SELECT DISTINCT mechanic FROM cards WHERE mechanic IS NOT NULL ORDER BY mechanic")
    ).scalars().all()
    archetypes = db.execute(
        text(
            "SELECT DISTINCT archetype FROM cards "
            "WHERE archetype IS NOT NULL AND archetype != '' "
            "ORDER BY archetype LIMIT :lim"
        ),
        {"lim": FILTER_ARCHETYPE_LIMIT},
    ).scalars().all()

    payload = {
        "categories": list(categories),
        "types": _distinct_type_labels(db),
        "mechanics": list(mechanics),
        "attributes": list(attributes),
        "archetypes": list(archetypes),
        "stat_ranges": _catalog_stat_ranges(db),
    }
    _catalog_filters_cache = payload
    _catalog_filters_cached_at = now
    return payload


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/status")
def status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        card_count = db.execute(select(func.count()).select_from(Card)).scalar() or 0
    except Exception:
        card_count = 0

    collection_count = 0
    deck_count = 0
    if card_count:
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
        "authenticated": True,
    }
    if not IS_PRODUCTION:
        from ygo_app.config import DB_PATH

        payload["database_exists"] = DB_PATH.exists() if DB_PATH else True
    return payload


def _distinct_type_labels(db: Session) -> list[str]:
    rows = db.execute(
        select(Card.types).where(Card.types.isnot(None), Card.types != "").distinct()
    ).scalars().all()
    labels: set[str] = set()
    for raw in rows:
        labels.update(parse_json_string_list(raw))
    return sorted(labels)


@router.get("/filters")
def filters(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from ygo_app.models import CollectionFolder

    folders = list(
        db.execute(
            select(CollectionFolder.name)
            .where(CollectionFolder.user_id == user.id)
            .order_by(CollectionFolder.sort_order, CollectionFolder.name)
        )
        .scalars()
        .all()
    )

    catalog = _load_catalog_filters(db)

    return {
        "folders": folders,
        **catalog,
    }
