from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, joinedload

from ygo_app.models import (
    Card,
    CollectionItem,
    Deck,
    DeckCard,
    Printing,
    User,
    UserCardTag,
    UserFavorite,
)
from ygo_app.search_index import fts_card_ids, ilike_text_filter
from ygo_app.utils import normalize_rarity_code, rarity_display


def _owned_by_card(
    session: Session, card_ids: list[int], user_id: int | None
) -> dict[int, int]:
    if not card_ids or user_id is None:
        return {}
    stmt = (
        select(Printing.card_id, func.coalesce(func.sum(CollectionItem.quantity), 0))
        .join(
            CollectionItem,
            (CollectionItem.set_code == Printing.set_code)
            & (CollectionItem.rarity_code == Printing.set_rarity_code)
            & (CollectionItem.user_id == user_id),
            isouter=False,
        )
        .where(Printing.card_id.in_(card_ids))
        .group_by(Printing.card_id)
    )
    return {row[0]: int(row[1]) for row in session.execute(stmt).all()}


def _favorite_card_ids(session: Session, user_id: int | None) -> set[int]:
    if user_id is None:
        return set()
    rows = session.execute(
        select(UserFavorite.card_id).where(UserFavorite.user_id == user_id)
    ).scalars().all()
    return set(rows)


def is_favorite(session: Session, user_id: int | None, card_id: int) -> bool:
    if user_id is None:
        return False
    return (
        session.execute(
            select(UserFavorite.id).where(
                UserFavorite.user_id == user_id,
                UserFavorite.card_id == card_id,
            )
        ).first()
        is not None
    )


def get_user_tags(session: Session, user_id: int | None, card_id: int) -> list[str]:
    if user_id is None:
        return []
    return list(
        session.execute(
            select(UserCardTag.tag)
            .where(UserCardTag.user_id == user_id, UserCardTag.card_id == card_id)
            .order_by(UserCardTag.tag)
        )
        .scalars()
        .all()
    )


def search_cards(
    session: Session,
    *,
    q: str | None = None,
    card_type: str | None = None,
    frame_type: str | None = None,
    attribute: str | None = None,
    race: str | None = None,
    archetype: str | None = None,
    set_code: str | None = None,
    owned_only: bool = False,
    favorites_only: bool = False,
    tag: str | None = None,
    user_id: int | None = None,
    limit: int = 60,
    offset: int = 0,
) -> tuple[list[Card], int]:
    stmt = select(Card)
    count_stmt = select(func.count()).select_from(Card)

    if set_code:
        stmt = stmt.join(Printing).where(Printing.set_code.ilike(f"%{set_code.strip()}%"))
        count_stmt = (
            select(func.count(func.distinct(Card.id)))
            .select_from(Card)
            .join(Printing)
            .where(Printing.set_code.ilike(f"%{set_code.strip()}%"))
        )
        stmt = stmt.distinct()

    if q:
        term = q.strip()
        if term.isdigit():
            stmt = stmt.where(Card.id == int(term))
            count_stmt = select(func.count()).select_from(Card).where(Card.id == int(term))
        else:
            fts_ids = fts_card_ids(session, term, limit=limit + offset)
            if fts_ids:
                stmt = stmt.where(Card.id.in_(fts_ids))
                count_stmt = select(func.count()).select_from(Card).where(Card.id.in_(fts_ids))
            else:
                filt = ilike_text_filter(term)
                stmt = stmt.where(filt)
                count_stmt = select(func.count()).select_from(Card).where(filt)

    if card_type:
        stmt = stmt.where(Card.type.ilike(f"%{card_type}%"))
        count_stmt = count_stmt.where(Card.type.ilike(f"%{card_type}%"))
    if frame_type:
        stmt = stmt.where(Card.frame_type == frame_type)
        count_stmt = count_stmt.where(Card.frame_type == frame_type)
    if attribute:
        stmt = stmt.where(Card.attribute == attribute)
        count_stmt = count_stmt.where(Card.attribute == attribute)
    if race:
        stmt = stmt.where(Card.race == race)
        count_stmt = count_stmt.where(Card.race == race)
    if archetype:
        stmt = stmt.where(Card.archetype.ilike(f"%{archetype}%"))
        count_stmt = count_stmt.where(Card.archetype.ilike(f"%{archetype}%"))

    if favorites_only and user_id is not None:
        stmt = stmt.join(UserFavorite).where(UserFavorite.user_id == user_id)
        count_stmt = (
            select(func.count(func.distinct(Card.id)))
            .select_from(Card)
            .join(UserFavorite)
            .where(UserFavorite.user_id == user_id)
        )
        stmt = stmt.distinct()
    elif favorites_only:
        return [], 0

    if tag and user_id is not None:
        stmt = stmt.join(UserCardTag).where(
            UserCardTag.user_id == user_id,
            UserCardTag.tag.ilike(tag.strip()),
        )
        count_stmt = (
            select(func.count(func.distinct(Card.id)))
            .select_from(Card)
            .join(UserCardTag)
            .where(
                UserCardTag.user_id == user_id,
                UserCardTag.tag.ilike(tag.strip()),
            )
        )
        stmt = stmt.distinct()
    elif tag:
        return [], 0

    if owned_only and user_id is not None:
        owned_ids = session.execute(
            select(Printing.card_id)
            .join(
                CollectionItem,
                (CollectionItem.set_code == Printing.set_code)
                & (CollectionItem.rarity_code == Printing.set_rarity_code)
                & (CollectionItem.user_id == user_id),
            )
            .distinct()
        ).scalars().all()
        if not owned_ids:
            return [], 0
        stmt = stmt.where(Card.id.in_(owned_ids))
        count_stmt = select(func.count()).select_from(Card).where(Card.id.in_(owned_ids))
    elif owned_only:
        return [], 0

    total = session.execute(count_stmt).scalar() or 0
    cards = (
        session.execute(stmt.order_by(Card.name).offset(offset).limit(limit))
        .scalars()
        .unique()
        .all()
    )
    return list(cards), int(total)


def card_to_summary(session: Session, card: Card, user_id: int | None) -> dict:
    if user_id is None:
        return {"owned": False, "owned_quantity": 0, "is_favorite": False}
    owned_qty = session.execute(
        select(func.coalesce(func.sum(CollectionItem.quantity), 0))
        .select_from(CollectionItem)
        .join(
            Printing,
            (CollectionItem.set_code == Printing.set_code)
            & (CollectionItem.rarity_code == Printing.set_rarity_code),
        )
        .where(Printing.card_id == card.id, CollectionItem.user_id == user_id)
    ).scalar()
    qty = int(owned_qty or 0)
    return {
        "owned": qty > 0,
        "owned_quantity": qty,
        "is_favorite": is_favorite(session, user_id, card.id),
    }


def get_card_detail(session: Session, card_id: int, user_id: int | None) -> Card | None:
    card = session.get(Card, card_id, options=[joinedload(Card.printings)])
    if not card:
        return None

    owned_map: dict[tuple[str, str], int] = {}
    if user_id is not None:
        rows = session.execute(
            select(
                CollectionItem.set_code,
                CollectionItem.rarity_code,
                func.sum(CollectionItem.quantity),
            )
            .join(
                Printing,
                (CollectionItem.set_code == Printing.set_code)
                & (CollectionItem.rarity_code == Printing.set_rarity_code),
            )
            .where(Printing.card_id == card_id, CollectionItem.user_id == user_id)
            .group_by(CollectionItem.set_code, CollectionItem.rarity_code)
        ).all()
        for set_code, rarity_code, qty in rows:
            owned_map[(set_code, rarity_code)] = int(qty or 0)

    for printing in card.printings:
        printing.owned_quantity = owned_map.get(
            (printing.set_code, printing.set_rarity_code), 0
        )
    card._user_tags = get_user_tags(session, user_id, card_id)  # type: ignore[attr-defined]
    card._is_favorite = is_favorite(session, user_id, card_id)  # type: ignore[attr-defined]
    return card


def find_card_by_set_code(session: Session, set_code: str) -> Card | None:
    printing = session.execute(
        select(Printing).where(Printing.set_code == set_code).limit(1)
    ).scalar_one_or_none()
    if not printing:
        return None
    return session.get(Card, printing.card_id)


def list_collection(
    session: Session,
    *,
    user_id: int,
    q: str | None = None,
    folder: str | None = None,
    set_code: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    stmt = select(CollectionItem).where(CollectionItem.user_id == user_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                CollectionItem.card_name.ilike(like),
                CollectionItem.set_code.ilike(like),
                CollectionItem.set_name.ilike(like),
            )
        )
    if folder:
        stmt = stmt.where(CollectionItem.folder_name == folder)
    if set_code:
        stmt = stmt.where(CollectionItem.set_code.ilike(f"%{set_code.strip()}%"))

    total = session.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar() or 0

    items = (
        session.execute(stmt.order_by(CollectionItem.set_code).offset(offset).limit(limit))
        .scalars()
        .all()
    )

    results = []
    for item in items:
        card = find_card_by_set_code(session, item.set_code)
        row = {c.name: getattr(item, c.name) for c in CollectionItem.__table__.columns}
        row["printing"] = row.pop("edition", None)
        results.append(
            {
                **row,
                "card_id": card.id if card else None,
                "image_url_small": card.image_url_small if card else None,
                "rarity_display": rarity_display(item.rarity_code),
            }
        )
    return results, int(total)


def deck_counts(session: Session, deck_id: int) -> dict[str, int]:
    rows = session.execute(
        select(DeckCard.zone, func.sum(DeckCard.quantity))
        .where(DeckCard.deck_id == deck_id)
        .group_by(DeckCard.zone)
    ).all()
    counts = {"main": 0, "extra": 0, "side": 0}
    for zone, qty in rows:
        counts[zone] = int(qty or 0)
    return counts


def add_collection_item(session: Session, user_id: int, data: dict) -> CollectionItem:
    rarity_code = normalize_rarity_code(data["rarity"])
    item = CollectionItem(
        user_id=user_id,
        set_code=data["set_code"].strip(),
        rarity_code=rarity_code,
        card_name=data.get("card_name"),
        expansion_code=data.get("expansion_code"),
        set_name=data.get("set_name"),
        quantity=data.get("quantity", 1),
        trade_quantity=data.get("trade_quantity", 0),
        condition=data.get("condition"),
        edition=data.get("printing"),
        language=data.get("language"),
        folder_name=data.get("folder_name"),
        price_bought=data.get("price_bought"),
        date_bought=data.get("date_bought"),
        notes=data.get("notes"),
        printing_id=session.execute(
            select(Printing.id)
            .where(Printing.set_code == data["set_code"].strip())
            .where(Printing.set_rarity_code == rarity_code)
            .limit(1)
        ).scalar(),
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def toggle_favorite(session: Session, user_id: int, card_id: int) -> bool:
    existing = session.execute(
        select(UserFavorite).where(
            UserFavorite.user_id == user_id,
            UserFavorite.card_id == card_id,
        )
    ).scalar_one_or_none()
    if existing:
        session.delete(existing)
        session.commit()
        return False
    session.add(UserFavorite(user_id=user_id, card_id=card_id))
    session.commit()
    return True


def add_user_tag(session: Session, user_id: int, card_id: int, tag: str) -> list[str]:
    tag = tag.strip()
    existing = session.execute(
        select(UserCardTag).where(
            UserCardTag.user_id == user_id,
            UserCardTag.card_id == card_id,
            UserCardTag.tag == tag,
        )
    ).scalar_one_or_none()
    if not existing:
        session.add(UserCardTag(user_id=user_id, card_id=card_id, tag=tag))
        session.commit()
    return get_user_tags(session, user_id, card_id)


def remove_user_tag(session: Session, user_id: int, card_id: int, tag: str) -> None:
    row = session.execute(
        select(UserCardTag).where(
            UserCardTag.user_id == user_id,
            UserCardTag.card_id == card_id,
            UserCardTag.tag == tag,
        )
    ).scalar_one_or_none()
    if row:
        session.delete(row)
        session.commit()
