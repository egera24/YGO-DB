from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, joinedload

from ygo_app.models import Card, CardTag, CollectionItem, Deck, DeckCard, Printing
from ygo_app.utils import normalize_rarity_code, rarity_display


def _owned_by_card(session: Session, card_ids: list[int]) -> dict[int, int]:
    if not card_ids:
        return {}
    stmt = (
        select(Printing.card_id, func.coalesce(func.sum(CollectionItem.quantity), 0))
        .join(
            CollectionItem,
            (CollectionItem.set_code == Printing.set_code)
            & (CollectionItem.rarity_code == Printing.set_rarity_code),
            isouter=False,
        )
        .where(Printing.card_id.in_(card_ids))
        .group_by(Printing.card_id)
    )
    return {row[0]: int(row[1]) for row in session.execute(stmt).all()}


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
    limit: int = 60,
    offset: int = 0,
) -> tuple[list[Card], int]:
    stmt = select(Card)
    count_stmt = select(func.count()).select_from(Card)

    if set_code:
        stmt = stmt.join(Printing).where(Printing.set_code.ilike(f"%{set_code.strip()}%"))
        count_stmt = count_stmt.join(Printing).where(Printing.set_code.ilike(f"%{set_code.strip()}%"))
        stmt = stmt.distinct()
        count_stmt = select(func.count(func.distinct(Card.id))).select_from(Card).join(Printing).where(
            Printing.set_code.ilike(f"%{set_code.strip()}%")
        )

    if q:
        term = q.strip()
        if term.isdigit():
            stmt = stmt.where(Card.id == int(term))
            count_stmt = select(func.count()).select_from(Card).where(Card.id == int(term))
        else:
            fts_query = " ".join(f'"{part}"' for part in term.split() if part)
            fts_ids = session.execute(
                text(
                    "SELECT rowid FROM cards_fts WHERE cards_fts MATCH :q ORDER BY rank LIMIT :lim"
                ),
                {"q": fts_query, "lim": limit + offset},
            ).scalars().all()
            if fts_ids:
                stmt = stmt.where(Card.id.in_(fts_ids))
                count_stmt = select(func.count()).select_from(Card).where(Card.id.in_(fts_ids))
            else:
                like = f"%{term}%"
                stmt = stmt.where(
                    or_(
                        Card.name.ilike(like),
                        Card.desc.ilike(like),
                        Card.archetype.ilike(like),
                    )
                )
                count_stmt = select(func.count()).select_from(Card).where(
                    or_(
                        Card.name.ilike(like),
                        Card.desc.ilike(like),
                        Card.archetype.ilike(like),
                    )
                )

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
    if favorites_only:
        stmt = stmt.where(Card.is_favorite.is_(True))
        count_stmt = count_stmt.where(Card.is_favorite.is_(True))
    if tag:
        stmt = stmt.join(CardTag).where(CardTag.tag.ilike(tag.strip()))
        count_stmt = count_stmt.join(CardTag).where(CardTag.tag.ilike(tag.strip()))
        stmt = stmt.distinct()

    if owned_only:
        owned_ids = session.execute(
            select(Printing.card_id)
            .join(
                CollectionItem,
                (CollectionItem.set_code == Printing.set_code)
                & (CollectionItem.rarity_code == Printing.set_rarity_code),
            )
            .distinct()
        ).scalars().all()
        if not owned_ids:
            return [], 0
        stmt = stmt.where(Card.id.in_(owned_ids))
        count_stmt = select(func.count()).select_from(Card).where(Card.id.in_(owned_ids))

    total = session.execute(count_stmt).scalar() or 0
    cards = (
        session.execute(stmt.order_by(Card.name).offset(offset).limit(limit))
        .scalars()
        .unique()
        .all()
    )
    return list(cards), int(total)


def card_to_summary(session: Session, card: Card) -> dict:
    owned_qty = session.execute(
        select(func.coalesce(func.sum(CollectionItem.quantity), 0))
        .select_from(CollectionItem)
        .join(
            Printing,
            (CollectionItem.set_code == Printing.set_code)
            & (CollectionItem.rarity_code == Printing.set_rarity_code),
        )
        .where(Printing.card_id == card.id)
    ).scalar()
    qty = int(owned_qty or 0)
    return {
        "owned": qty > 0,
        "owned_quantity": qty,
    }


def get_card_detail(session: Session, card_id: int) -> Card | None:
    card = session.get(
        Card,
        card_id,
        options=[joinedload(Card.printings), joinedload(Card.tags)],
    )
    if not card:
        return None

    owned_map: dict[tuple[str, str], int] = {}
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
        .where(Printing.card_id == card_id)
        .group_by(CollectionItem.set_code, CollectionItem.rarity_code)
    ).all()
    for set_code, rarity_code, qty in rows:
        owned_map[(set_code, rarity_code)] = int(qty or 0)

    for printing in card.printings:
        printing.owned_quantity = owned_map.get(
            (printing.set_code, printing.set_rarity_code), 0
        )
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
    q: str | None = None,
    folder: str | None = None,
    set_code: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    stmt = select(CollectionItem)
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


def add_collection_item(session: Session, data: dict) -> CollectionItem:
    rarity_code = normalize_rarity_code(data["rarity"])
    item = CollectionItem(
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
