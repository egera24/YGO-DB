from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, joinedload

import json
from datetime import datetime

from ygo_app.models import (
    Card,
    CollectionItem,
    Deck,
    DeckCard,
    Printing,
    SearchPreset,
    User,
    UserCardTag,
    UserFavorite,
)
from ygo_app.card_filters import (
    link_markers_contain_all,
    parse_multi_param,
    types_overlap_filter,
)
from ygo_app.search_query import (
    SearchQueryError,
    Term,
    compile_search_filter,
    text_search_filter,
)
from ygo_app.utils import normalize_rarity_code, rarity_display


class SearchPresetConflictError(Exception):
    """Raised when a preset name already exists for the user."""


def _preset_params_from_db(raw: str) -> dict[str, str]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def _preset_params_to_db(params: dict[str, str]) -> str:
    return json.dumps(params, sort_keys=True)


def _search_preset_out(preset: SearchPreset) -> dict:
    return {
        "id": preset.id,
        "name": preset.name,
        "params": _preset_params_from_db(preset.params),
        "created_at": preset.created_at,
        "updated_at": preset.updated_at,
    }


def list_search_presets(session: Session, user_id: int) -> list[SearchPreset]:
    return (
        session.execute(
            select(SearchPreset)
            .where(SearchPreset.user_id == user_id)
            .order_by(SearchPreset.name.asc())
        )
        .scalars()
        .all()
    )


def get_search_preset(
    session: Session, preset_id: int, user_id: int
) -> SearchPreset | None:
    preset = session.get(SearchPreset, preset_id)
    if not preset or preset.user_id != user_id:
        return None
    return preset


def get_search_preset_by_name(
    session: Session, user_id: int, name: str
) -> SearchPreset | None:
    return session.execute(
        select(SearchPreset).where(
            SearchPreset.user_id == user_id,
            SearchPreset.name == name.strip(),
        )
    ).scalar_one_or_none()


def create_search_preset(
    session: Session,
    user_id: int,
    name: str,
    params: dict[str, str],
    *,
    overwrite: bool = False,
) -> SearchPreset:
    name = name.strip()
    existing = get_search_preset_by_name(session, user_id, name)
    if existing:
        if not overwrite:
            raise SearchPresetConflictError(name)
        existing.params = _preset_params_to_db(params)
        existing.updated_at = datetime.utcnow()
        session.commit()
        session.refresh(existing)
        return existing

    preset = SearchPreset(
        user_id=user_id,
        name=name,
        params=_preset_params_to_db(params),
    )
    session.add(preset)
    session.commit()
    session.refresh(preset)
    return preset


def update_search_preset(
    session: Session,
    preset_id: int,
    user_id: int,
    *,
    name: str | None = None,
    params: dict[str, str] | None = None,
) -> SearchPreset | None:
    preset = get_search_preset(session, preset_id, user_id)
    if not preset:
        return None

    if name is not None and name != preset.name:
        conflict = get_search_preset_by_name(session, user_id, name)
        if conflict and conflict.id != preset.id:
            raise SearchPresetConflictError(name)
        preset.name = name

    if params is not None:
        preset.params = _preset_params_to_db(params)

    preset.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(preset)
    return preset


def delete_search_preset(session: Session, preset_id: int, user_id: int) -> bool:
    preset = get_search_preset(session, preset_id, user_id)
    if not preset:
        return False
    session.delete(preset)
    session.commit()
    return True


def _apply_int_range(column, min_val: int | None, max_val: int | None):
    clauses = []
    if min_val is not None:
        clauses.append(column >= min_val)
    if max_val is not None:
        clauses.append(column <= max_val)
    return clauses


def summoning_condition_suggestions(
    session: Session, *, q: str, limit: int = 20
) -> list[str]:
    term = q.strip()
    if not term:
        return []
    pattern = f"%{term}%"
    rows = session.execute(
        select(Card.summoning_condition)
        .where(
            Card.summoning_condition.isnot(None),
            Card.summoning_condition != "",
            Card.summoning_condition.ilike(pattern),
        )
        .distinct()
        .order_by(Card.summoning_condition)
        .limit(limit)
    ).scalars().all()
    return [r for r in rows if r]


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
    category: str | None = None,
    types: str | None = None,
    mechanic: str | None = None,
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
            try:
                filt = text_search_filter(term)
            except SearchQueryError:
                filt = compile_search_filter(Term(term))
            if filt is not None:
                stmt = stmt.where(filt)
                count_stmt = count_stmt.where(filt)

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

    categories = parse_multi_param(category)
    if categories:
        stmt = stmt.where(Card.category.in_(categories))
        count_stmt = count_stmt.where(Card.category.in_(categories))

    type_labels = parse_multi_param(types)
    types_filt = types_overlap_filter(type_labels)
    if types_filt is not None:
        stmt = stmt.where(types_filt)
        count_stmt = count_stmt.where(types_filt)

    mechanics = parse_multi_param(mechanic)
    if mechanics:
        mech_filt = or_(*[Card.mechanic == m for m in mechanics])
        stmt = stmt.where(mech_filt)
        count_stmt = count_stmt.where(mech_filt)

    attrs = parse_multi_param(attribute)
    if attrs:
        attr_filt = or_(*[Card.attribute == a for a in attrs])
        stmt = stmt.where(attr_filt)
        count_stmt = count_stmt.where(attr_filt)

    if summoning_condition and summoning_condition.strip():
        pattern = f"%{summoning_condition.strip()}%"
        stmt = stmt.where(Card.summoning_condition.ilike(pattern))
        count_stmt = count_stmt.where(Card.summoning_condition.ilike(pattern))

    marker_labels = parse_multi_param(link_markers)
    marker_clauses = link_markers_contain_all(marker_labels)
    if marker_clauses:
        for clause in marker_clauses:
            stmt = stmt.where(clause)
            count_stmt = count_stmt.where(clause)

    for column, lo, hi in (
        (Card.atk, atk_min, atk_max),
        (Card.def_, def_min, def_max),
        (Card.level, level_min, level_max),
        (Card.rank, rank_min, rank_max),
        (Card.link_rating, link_rating_min, link_rating_max),
        (Card.pendulum_scale, pendulum_scale_min, pendulum_scale_max),
    ):
        for clause in _apply_int_range(column, lo, hi):
            stmt = stmt.where(clause)
            count_stmt = count_stmt.where(clause)

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


def card_summaries_batch(
    session: Session, cards: list[Card], user_id: int | None
) -> dict[int, dict]:
    if not cards:
        return {}
    if user_id is None:
        return {
            c.id: {"owned": False, "owned_quantity": 0, "is_favorite": False} for c in cards
        }
    card_ids = [c.id for c in cards]
    owned_map = _owned_by_card(session, card_ids, user_id)
    fav_ids = set(
        session.execute(
            select(UserFavorite.card_id).where(
                UserFavorite.user_id == user_id,
                UserFavorite.card_id.in_(card_ids),
            )
        )
        .scalars()
        .all()
    )
    return {
        cid: {
            "owned": owned_map.get(cid, 0) > 0,
            "owned_quantity": owned_map.get(cid, 0),
            "is_favorite": cid in fav_ids,
        }
        for cid in card_ids
    }


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


UNASSIGNED_FOLDER = "__unassigned__"

_COLLECTION_SORT_COLUMNS = {
    "set_code": CollectionItem.set_code,
    "card_name": CollectionItem.card_name,
    "folder_name": CollectionItem.folder_name,
    "quantity": CollectionItem.quantity,
}


def find_card_by_set_code(session: Session, set_code: str) -> Card | None:
    printing = session.execute(
        select(Printing).where(Printing.set_code == set_code).limit(1)
    ).scalar_one_or_none()
    if not printing:
        return None
    return session.get(Card, printing.card_id)


def _cards_by_set_codes(session: Session, set_codes: set[str]) -> dict[str, Card | None]:
    if not set_codes:
        return {}
    rows = session.execute(
        select(Printing.set_code, Card)
        .join(Card, Printing.card_id == Card.id)
        .where(Printing.set_code.in_(set_codes))
    ).all()
    result: dict[str, Card | None] = dict.fromkeys(set_codes)
    for set_code, card in rows:
        if result[set_code] is None:
            result[set_code] = card
    return result


def _card_for_collection_item(
    item: CollectionItem,
    *,
    set_code_fallback: dict[str, Card | None] | None = None,
) -> Card | None:
    printing = item.linked_printing
    if printing is not None and printing.card is not None:
        return printing.card
    if set_code_fallback is not None:
        return set_code_fallback.get(item.set_code)
    return None


def _collection_item_row(
    item: CollectionItem,
    *,
    set_code_fallback: dict[str, Card | None] | None = None,
) -> dict:
    card = _card_for_collection_item(item, set_code_fallback=set_code_fallback)
    row = {c.name: getattr(item, c.name) for c in CollectionItem.__table__.columns}
    row["printing"] = row.pop("edition", None)
    return {
        **row,
        "card_id": card.id if card else None,
        "image_url_small": card.image_url_small if card else None,
        "rarity_display": rarity_display(item.rarity_code),
    }


def _apply_collection_folder_filter(stmt, folder: str | None):
    if not folder:
        return stmt
    if folder == UNASSIGNED_FOLDER:
        return stmt.where(
            or_(
                CollectionItem.folder_name.is_(None),
                CollectionItem.folder_name == "",
            )
        )
    return stmt.where(CollectionItem.folder_name == folder)


def list_collection(
    session: Session,
    *,
    user_id: int,
    q: str | None = None,
    folder: str | None = None,
    set_code: str | None = None,
    sort: str = "set_code",
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
    stmt = _apply_collection_folder_filter(stmt, folder)
    if set_code:
        stmt = stmt.where(CollectionItem.set_code.ilike(f"%{set_code.strip()}%"))

    total = session.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar() or 0

    order_col = _COLLECTION_SORT_COLUMNS.get(sort, CollectionItem.set_code)
    items = (
        session.execute(
            stmt.options(
                joinedload(CollectionItem.linked_printing).joinedload(Printing.card)
            )
            .order_by(order_col)
            .offset(offset)
            .limit(limit)
        )
        .unique()
        .scalars()
        .all()
    )

    missing_codes = {
        item.set_code
        for item in items
        if _card_for_collection_item(item) is None
    }
    fallback_map = _cards_by_set_codes(session, missing_codes)

    results = [
        _collection_item_row(item, set_code_fallback=fallback_map) for item in items
    ]
    return results, int(total)


def collection_stats(session: Session, *, user_id: int) -> dict:
    total_items = (
        session.execute(
            select(func.count())
            .select_from(CollectionItem)
            .where(CollectionItem.user_id == user_id)
        ).scalar()
        or 0
    )
    total_quantity = (
        session.execute(
            select(func.coalesce(func.sum(CollectionItem.quantity), 0)).where(
                CollectionItem.user_id == user_id
            )
        ).scalar()
        or 0
    )
    unassigned_count = (
        session.execute(
            select(func.count())
            .select_from(CollectionItem)
            .where(
                CollectionItem.user_id == user_id,
                or_(
                    CollectionItem.folder_name.is_(None),
                    CollectionItem.folder_name == "",
                ),
            )
        ).scalar()
        or 0
    )
    unassigned_quantity = (
        session.execute(
            select(func.coalesce(func.sum(CollectionItem.quantity), 0)).where(
                CollectionItem.user_id == user_id,
                or_(
                    CollectionItem.folder_name.is_(None),
                    CollectionItem.folder_name == "",
                ),
            )
        ).scalar()
        or 0
    )

    folder_rows = session.execute(
        select(
            CollectionItem.folder_name,
            func.count(),
            func.coalesce(func.sum(CollectionItem.quantity), 0),
        )
        .where(
            CollectionItem.user_id == user_id,
            CollectionItem.folder_name.isnot(None),
            CollectionItem.folder_name != "",
        )
        .group_by(CollectionItem.folder_name)
        .order_by(CollectionItem.folder_name)
    ).all()

    return {
        "total_items": int(total_items),
        "total_quantity": int(total_quantity),
        "unique_printings": int(total_items),
        "unassigned_count": int(unassigned_count),
        "unassigned_quantity": int(unassigned_quantity),
        "folders": [
            {
                "name": name,
                "item_count": int(item_count),
                "quantity": int(qty),
            }
            for name, item_count, qty in folder_rows
        ],
    }


def rename_collection_folder(
    session: Session,
    *,
    user_id: int,
    from_name: str,
    to_name: str,
) -> int:
    from_clean = from_name.strip()
    to_clean = to_name.strip()
    if not from_clean or not to_clean:
        raise ValueError("from_name and to_name are required")
    rows = session.execute(
        select(CollectionItem).where(
            CollectionItem.user_id == user_id,
            CollectionItem.folder_name == from_clean,
        )
    ).scalars().all()
    for item in rows:
        item.folder_name = to_clean
    session.commit()
    return len(rows)


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
