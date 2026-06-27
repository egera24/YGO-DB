from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, joinedload, load_only

import json
from datetime import datetime

from ygo_app.models import (
    Card,
    CollectionFolder,
    CollectionItem,
    CollectionItemFolder,
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
from ygo_app.cardmarket.market_prices import load_market_prices
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


def _normalize_int_range(
    lo: int | None, hi: int | None
) -> tuple[int | None, int | None]:
    if lo is not None and hi is not None and lo > hi:
        return hi, lo
    return lo, hi


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


def _trade_by_card(
    session: Session, card_ids: list[int], user_id: int | None
) -> dict[int, int]:
    if not card_ids or user_id is None:
        return {}
    stmt = (
        select(
            Printing.card_id,
            func.coalesce(func.sum(CollectionItem.trade_quantity), 0),
        )
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


def list_user_tags(
    session: Session,
    user_id: int,
    q: str | None = None,
    limit: int = 200,
) -> list[str]:
    stmt = (
        select(UserCardTag.tag)
        .where(UserCardTag.user_id == user_id)
        .distinct()
        .order_by(UserCardTag.tag)
    )
    if q and q.strip():
        stmt = stmt.where(UserCardTag.tag.ilike(f"{q.strip()}%"))
    stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars().all())


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
    search_columns = (
        Card.id,
        Card.name,
        Card.type,
        Card.frame_type,
        Card.atk,
        Card.def_,
        Card.level,
        Card.race,
        Card.attribute,
        Card.archetype,
        Card.category,
        Card.types,
        Card.mechanic,
        Card.rank,
        Card.link_rating,
        Card.pendulum_scale,
        Card.link_markers,
        Card.summoning_condition,
        Card.image_url_small,
        Card.image_url,
        Card.linkval,
        Card.scale,
    )
    stmt = select(Card).options(load_only(*search_columns))
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

    atk_min, atk_max = _normalize_int_range(atk_min, atk_max)
    def_min, def_max = _normalize_int_range(def_min, def_max)
    level_min, level_max = _normalize_int_range(level_min, level_max)
    rank_min, rank_max = _normalize_int_range(rank_min, rank_max)
    link_rating_min, link_rating_max = _normalize_int_range(
        link_rating_min, link_rating_max
    )
    pendulum_scale_min, pendulum_scale_max = _normalize_int_range(
        pendulum_scale_min, pendulum_scale_max
    )

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
            c.id: {
                "owned": False,
                "owned_quantity": 0,
                "trade_quantity": 0,
                "is_favorite": False,
            }
            for c in cards
        }
    card_ids = [c.id for c in cards]
    owned_map = _owned_by_card(session, card_ids, user_id)
    trade_map = _trade_by_card(session, card_ids, user_id)
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
            "trade_quantity": trade_map.get(cid, 0),
            "is_favorite": cid in fav_ids,
        }
        for cid in card_ids
    }


def card_to_summary(session: Session, card: Card, user_id: int | None) -> dict:
    if user_id is None:
        return {
            "owned": False,
            "owned_quantity": 0,
            "trade_quantity": 0,
            "is_favorite": False,
        }
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
    trade_qty = session.execute(
        select(func.coalesce(func.sum(CollectionItem.trade_quantity), 0))
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
        "trade_quantity": int(trade_qty or 0),
        "is_favorite": is_favorite(session, user_id, card.id),
    }


def get_card_detail(session: Session, card_id: int, user_id: int | None) -> Card | None:
    card = session.get(
        Card,
        card_id,
        options=[
            joinedload(Card.printings),
            joinedload(Card.errata_versions),
        ],
    )
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

    from ygo_app.cardmarket.market_prices import attach_market_prices_to_printings

    attach_market_prices_to_printings(session, list(card.printings))
    card._user_tags = get_user_tags(session, user_id, card_id)  # type: ignore[attr-defined]
    card._is_favorite = is_favorite(session, user_id, card_id)  # type: ignore[attr-defined]
    return card


NO_FOLDER = "__no_folder__"
RESERVED_FOLDER_NAME_KEYS = frozenset({"no folder"})


class FolderConflictError(Exception):
    """Raised when a folder name already exists for the user."""


def normalize_folder_name(name: str) -> str:
    return name.strip()


def folder_name_key(name: str) -> str:
    return normalize_folder_name(name).lower()


def _folder_allocations_for_row(item: CollectionItem) -> list[dict]:
    allocations = sorted(
        item.folder_allocations,
        key=lambda row: (
            row.folder.name.lower() if row.folder else "",
            row.folder_id or 0,
        ),
    )
    return [
        {
            "folder_id": row.folder_id,
            "name": row.folder.name if row.folder else None,
            "quantity": int(row.quantity),
        }
        for row in allocations
    ]


def _default_folder_allocations(quantity: int) -> list[dict]:
    return [{"folder_id": None, "quantity": quantity}]


def get_or_create_folder(
    session: Session, user_id: int, name: str
) -> CollectionFolder | None:
    clean = normalize_folder_name(name)
    if not clean:
        return None
    key = folder_name_key(clean)
    if key in RESERVED_FOLDER_NAME_KEYS:
        raise ValueError('Folder name "No Folder" is reserved')
    existing = session.execute(
        select(CollectionFolder).where(
            CollectionFolder.user_id == user_id,
            CollectionFolder.name_key == key,
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    folder = CollectionFolder(user_id=user_id, name=clean, name_key=key)
    session.add(folder)
    session.flush()
    return folder


def list_collection_folders(session: Session, *, user_id: int) -> list[dict]:
    folders = session.execute(
        select(CollectionFolder)
        .where(CollectionFolder.user_id == user_id)
        .order_by(CollectionFolder.sort_order, CollectionFolder.name)
    ).scalars().all()

    stats_rows = session.execute(
        select(
            CollectionItemFolder.folder_id,
            func.count(func.distinct(CollectionItemFolder.collection_item_id)),
            func.coalesce(func.sum(CollectionItemFolder.quantity), 0),
        )
        .join(CollectionItem, CollectionItem.id == CollectionItemFolder.collection_item_id)
        .where(CollectionItem.user_id == user_id, CollectionItemFolder.folder_id.isnot(None))
        .group_by(CollectionItemFolder.folder_id)
    ).all()
    stats_by_id = {
        folder_id: (int(item_count), int(qty))
        for folder_id, item_count, qty in stats_rows
    }

    return [
        {
            "id": folder.id,
            "name": folder.name,
            "sort_order": folder.sort_order,
            "item_count": stats_by_id.get(folder.id, (0, 0))[0],
            "quantity": stats_by_id.get(folder.id, (0, 0))[1],
        }
        for folder in folders
    ]


def create_collection_folder(session: Session, *, user_id: int, name: str) -> CollectionFolder:
    clean = normalize_folder_name(name)
    if not clean:
        raise ValueError("Folder name is required")
    key = folder_name_key(clean)
    if key in RESERVED_FOLDER_NAME_KEYS:
        raise ValueError('Folder name "No Folder" is reserved')
    existing = session.execute(
        select(CollectionFolder).where(
            CollectionFolder.user_id == user_id,
            CollectionFolder.name_key == key,
        )
    ).scalar_one_or_none()
    if existing:
        raise FolderConflictError(f"Folder '{existing.name}' already exists")
    folder = CollectionFolder(user_id=user_id, name=clean, name_key=key)
    session.add(folder)
    session.commit()
    session.refresh(folder)
    return folder


def update_collection_folder(
    session: Session,
    *,
    user_id: int,
    folder_id: int,
    name: str | None = None,
    sort_order: int | None = None,
) -> CollectionFolder:
    folder = session.get(CollectionFolder, folder_id)
    if not folder or folder.user_id != user_id:
        raise ValueError("Folder not found")
    if name is not None:
        clean = normalize_folder_name(name)
        if not clean:
            raise ValueError("Folder name is required")
        key = folder_name_key(clean)
        if key in RESERVED_FOLDER_NAME_KEYS:
            raise ValueError('Folder name "No Folder" is reserved')
        conflict = session.execute(
            select(CollectionFolder).where(
                CollectionFolder.user_id == user_id,
                CollectionFolder.name_key == key,
                CollectionFolder.id != folder_id,
            )
        ).scalar_one_or_none()
        if conflict:
            raise FolderConflictError(f"Folder '{conflict.name}' already exists")
        folder.name = clean
        folder.name_key = key
    if sort_order is not None:
        folder.sort_order = sort_order
    session.commit()
    session.refresh(folder)
    return folder


def delete_collection_folder(
    session: Session, *, user_id: int, folder_id: int
) -> tuple[int, int]:
    folder = session.get(CollectionFolder, folder_id)
    if not folder or folder.user_id != user_id:
        raise ValueError("Folder not found")
    allocations = (
        session.execute(
            select(CollectionItemFolder)
            .join(
                CollectionItem,
                CollectionItem.id == CollectionItemFolder.collection_item_id,
            )
            .where(
                CollectionItem.user_id == user_id,
                CollectionItemFolder.folder_id == folder_id,
            )
            .options(
                joinedload(CollectionItemFolder.collection_item).joinedload(
                    CollectionItem.folder_allocations
                )
            )
        )
        .unique()
        .scalars()
        .all()
    )
    moved_allocations = 0
    moved_quantity = 0
    for allocation in allocations:
        item = allocation.collection_item
        moved_allocations += 1
        moved_quantity += int(allocation.quantity)
        no_folder = next(
            (row for row in item.folder_allocations if row.folder_id is None),
            None,
        )
        if no_folder:
            no_folder.quantity += allocation.quantity
            session.delete(allocation)
        else:
            allocation.folder_id = None
    session.delete(folder)
    session.commit()
    return moved_allocations, moved_quantity


def _validate_folder_allocations(
    session: Session,
    *,
    user_id: int,
    item: CollectionItem,
    allocations: list[dict],
) -> list[dict]:
    if not allocations:
        raise ValueError("At least one folder allocation is required")
    merged: dict[int | None, int] = {}
    for row in allocations:
        folder_id = row.get("folder_id")
        qty = int(row["quantity"])
        if qty < 1:
            raise ValueError("Allocation quantity must be at least 1")
        if folder_id is not None:
            folder = session.get(CollectionFolder, folder_id)
            if not folder or folder.user_id != user_id:
                raise ValueError("Folder not found")
        merged[folder_id] = merged.get(folder_id, 0) + qty
    total = sum(merged.values())
    if total != item.quantity:
        raise ValueError(
            f"Folder allocations must sum to item quantity ({item.quantity}), got {total}"
        )
    return [{"folder_id": key, "quantity": value} for key, value in merged.items()]


def set_item_folder_allocations(
    session: Session,
    *,
    user_id: int,
    item: CollectionItem,
    allocations: list[dict],
) -> None:
    normalized = _validate_folder_allocations(
        session, user_id=user_id, item=item, allocations=allocations
    )
    item.folder_allocations.clear()
    session.flush()
    for row in normalized:
        item.folder_allocations.append(
            CollectionItemFolder(
                folder_id=row["folder_id"],
                quantity=row["quantity"],
            )
        )


def _reconcile_allocations_after_quantity_change(item: CollectionItem) -> None:
    allocations = list(item.folder_allocations)
    if not allocations:
        item.folder_allocations.append(
            CollectionItemFolder(folder_id=None, quantity=item.quantity)
        )
        return
    if len(allocations) == 1:
        allocations[0].quantity = item.quantity
        return
    current_total = sum(int(row.quantity) for row in allocations)
    diff = item.quantity - current_total
    if diff == 0:
        return
    no_folder = next((row for row in allocations if row.folder_id is None), None)
    if no_folder:
        no_folder.quantity = max(1, no_folder.quantity + diff)
    elif diff > 0:
        item.folder_allocations.append(
            CollectionItemFolder(folder_id=None, quantity=diff)
        )
    else:
        raise ValueError(
            "Reduce folder allocations before lowering total quantity"
        )


def _ensure_default_allocations(item: CollectionItem) -> None:
    if not item.folder_allocations:
        item.folder_allocations.append(
            CollectionItemFolder(folder_id=None, quantity=item.quantity)
        )


_COLLECTION_SORT_COLUMNS = {
    "set_code": CollectionItem.set_code,
    "card_name": CollectionItem.card_name,
    "quantity": CollectionItem.quantity,
    "trade_quantity": CollectionItem.trade_quantity,
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
    folder_filter: str | None = None,
) -> dict:
    card = _card_for_collection_item(item, set_code_fallback=set_code_fallback)
    linked = item.linked_printing
    rarity_name = linked.set_rarity if linked is not None else None
    row = {c.name: getattr(item, c.name) for c in CollectionItem.__table__.columns}
    row["printing"] = row.pop("edition", None)
    folders = _folder_allocations_for_row(item)
    display_quantity = item.quantity
    if folder_filter == NO_FOLDER:
        alloc = next((f for f in folders if f["folder_id"] is None), None)
        display_quantity = alloc["quantity"] if alloc else 0
    elif folder_filter and folder_filter != NO_FOLDER:
        folder_id = int(folder_filter)
        alloc = next((f for f in folders if f["folder_id"] == folder_id), None)
        display_quantity = alloc["quantity"] if alloc else 0
    return {
        **row,
        "quantity": display_quantity,
        "card_id": card.id if card else None,
        "image_url_small": card.image_url_small if card else None,
        "rarity_display": rarity_display(item.rarity_code),
        "rarity_name": rarity_name,
        "folders": folders,
    }


def _apply_collection_folder_filter(stmt, folder: str | None):
    if not folder:
        return stmt
    if folder == NO_FOLDER:
        return stmt.where(
            CollectionItem.id.in_(
                select(CollectionItemFolder.collection_item_id).where(
                    CollectionItemFolder.folder_id.is_(None)
                )
            )
        )
    folder_id = int(folder)
    return stmt.where(
        CollectionItem.id.in_(
            select(CollectionItemFolder.collection_item_id).where(
                CollectionItemFolder.folder_id == folder_id
            )
        )
    )


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

    if sort == "folder_name":
        primary_folder = (
            select(CollectionFolder.name)
            .join(
                CollectionItemFolder,
                CollectionItemFolder.folder_id == CollectionFolder.id,
            )
            .where(CollectionItemFolder.collection_item_id == CollectionItem.id)
            .order_by(CollectionFolder.name)
            .limit(1)
            .scalar_subquery()
        )
        order_col = primary_folder
    else:
        order_col = _COLLECTION_SORT_COLUMNS.get(sort, CollectionItem.set_code)

    items = (
        session.execute(
            stmt.options(
                joinedload(CollectionItem.linked_printing).joinedload(Printing.card),
                joinedload(CollectionItem.folder_allocations).joinedload(
                    CollectionItemFolder.folder
                ),
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
        _collection_item_row(
            item, set_code_fallback=fallback_map, folder_filter=folder
        )
        for item in items
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
    no_folder_count = (
        session.execute(
            select(func.count(func.distinct(CollectionItemFolder.collection_item_id)))
            .join(CollectionItem, CollectionItem.id == CollectionItemFolder.collection_item_id)
            .where(
                CollectionItem.user_id == user_id,
                CollectionItemFolder.folder_id.is_(None),
            )
        ).scalar()
        or 0
    )
    no_folder_quantity = (
        session.execute(
            select(func.coalesce(func.sum(CollectionItemFolder.quantity), 0))
            .join(CollectionItem, CollectionItem.id == CollectionItemFolder.collection_item_id)
            .where(
                CollectionItem.user_id == user_id,
                CollectionItemFolder.folder_id.is_(None),
            )
        ).scalar()
        or 0
    )

    folder_rows = session.execute(
        select(
            CollectionFolder.id,
            CollectionFolder.name,
            func.count(func.distinct(CollectionItemFolder.collection_item_id)),
            func.coalesce(func.sum(CollectionItemFolder.quantity), 0),
        )
        .outerjoin(
            CollectionItemFolder,
            CollectionItemFolder.folder_id == CollectionFolder.id,
        )
        .outerjoin(CollectionItem, CollectionItem.id == CollectionItemFolder.collection_item_id)
        .where(CollectionFolder.user_id == user_id)
        .group_by(CollectionFolder.id, CollectionFolder.name)
        .order_by(CollectionFolder.sort_order, CollectionFolder.name)
    ).all()

    return {
        "total_items": int(total_items),
        "total_quantity": int(total_quantity),
        "unique_printings": int(total_items),
        "no_folder_count": int(no_folder_count),
        "no_folder_quantity": int(no_folder_quantity),
        "folders": [
            {
                "id": folder_id,
                "name": name,
                "item_count": int(item_count),
                "quantity": int(qty),
            }
            for folder_id, name, item_count, qty in folder_rows
        ],
    }


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


_DECK_ZONE_ORDER = {"main": 0, "extra": 1, "side": 2}


def _deck_zone_sort_key(zone: str) -> int:
    return _DECK_ZONE_ORDER.get(zone, 99)


def _deck_card_entries_for_decks(
    session: Session, deck_ids: list[int]
) -> dict[int, list[tuple[DeckCard, Card]]]:
    if not deck_ids:
        return {}
    rows = session.execute(
        select(DeckCard, Card)
        .join(Card, DeckCard.card_id == Card.id)
        .where(DeckCard.deck_id.in_(deck_ids))
    ).all()
    grouped: dict[int, list[tuple[DeckCard, Card]]] = {did: [] for did in deck_ids}
    for dc, card in rows:
        grouped[dc.deck_id].append((dc, card))
    for deck_id in deck_ids:
        grouped[deck_id].sort(
            key=lambda t: (_deck_zone_sort_key(t[0].zone), t[0].card_id)
        )
    return grouped


def compute_deck_preview_cards(
    preview_card_id: int | None,
    entries: list[tuple[DeckCard, Card]],
) -> list[dict]:
    """Up to 3 distinct cards for list tile stack; front card first."""
    if not entries:
        return []
    seen: set[int] = set()
    unique: list[tuple[int, str | None]] = []
    for _dc, card in entries:
        if card.id not in seen:
            seen.add(card.id)
            unique.append((card.id, card.image_url))
    if not unique:
        return []
    front_id = preview_card_id if preview_card_id in seen else unique[0][0]
    ordered: list[tuple[int, str | None]] = []
    for card_id, image_url in unique:
        if card_id == front_id:
            ordered.insert(0, (card_id, image_url))
        else:
            ordered.append((card_id, image_url))
    return [
        {"card_id": card_id, "image_url": image_url}
        for card_id, image_url in ordered[:3]
    ]


def list_user_decks(
    session: Session,
    user_id: int,
    *,
    q: str | None = None,
    sort: str = "updated_at",
) -> list[Deck]:
    stmt = select(Deck).where(Deck.user_id == user_id)
    if q and q.strip():
        term = f"%{q.strip()}%"
        card_match = (
            select(DeckCard.deck_id)
            .join(Card, DeckCard.card_id == Card.id)
            .where(Card.name.ilike(term))
            .distinct()
        )
        stmt = stmt.where(or_(Deck.name.ilike(term), Deck.id.in_(card_match)))
    if sort == "name":
        stmt = stmt.order_by(Deck.name.asc(), Deck.id.asc())
    elif sort == "created_at":
        stmt = stmt.order_by(Deck.created_at.desc(), Deck.id.desc())
    else:
        stmt = stmt.order_by(Deck.updated_at.desc(), Deck.id.desc())
    return list(session.execute(stmt).scalars().all())


def build_deck_out(
    deck: Deck,
    counts: dict[str, int],
    preview_cards: list[dict],
) -> dict:
    card_count = counts.get("main", 0) + counts.get("extra", 0) + counts.get("side", 0)
    return {
        "id": deck.id,
        "name": deck.name,
        "description": deck.description,
        "created_at": deck.created_at,
        "updated_at": deck.updated_at,
        "preview_card_id": deck.preview_card_id,
        "preview_cards": preview_cards,
        "main_count": counts.get("main", 0),
        "extra_count": counts.get("extra", 0),
        "side_count": counts.get("side", 0),
        "card_count": card_count,
    }


def list_decks_enriched(
    session: Session,
    user_id: int,
    *,
    q: str | None = None,
    sort: str = "updated_at",
) -> list[dict]:
    decks = list_user_decks(session, user_id, q=q, sort=sort)
    if not decks:
        return []
    deck_ids = [d.id for d in decks]
    entries_by_deck = _deck_card_entries_for_decks(session, deck_ids)
    result = []
    for deck in decks:
        counts = deck_counts(session, deck.id)
        entries = entries_by_deck.get(deck.id, [])
        previews = compute_deck_preview_cards(deck.preview_card_id, entries)
        result.append(build_deck_out(deck, counts, previews))
    return result


def clear_deck_preview_if_removed(session: Session, deck_id: int, card_id: int) -> None:
    deck = session.get(Deck, deck_id)
    if not deck or deck.preview_card_id != card_id:
        return
    still_in = session.execute(
        select(DeckCard.id).where(
            DeckCard.deck_id == deck_id,
            DeckCard.card_id == card_id,
        )
    ).scalar_one_or_none()
    if still_in is None:
        deck.preview_card_id = None


def update_deck(session: Session, deck: Deck, updates: dict) -> Deck:
    if "name" in updates and updates["name"] is not None:
        deck.name = updates["name"].strip()
    if "description" in updates:
        deck.description = updates["description"]
    if "preview_card_id" in updates:
        preview_card_id = updates["preview_card_id"]
        if preview_card_id is not None:
            in_deck = session.execute(
                select(DeckCard.id).where(
                    DeckCard.deck_id == deck.id,
                    DeckCard.card_id == preview_card_id,
                )
            ).scalar_one_or_none()
            if not in_deck:
                raise ValueError("Preview card must be in the deck")
        deck.preview_card_id = preview_card_id
    deck.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(deck)
    return deck


def _default_collection_prices(
    session: Session,
    *,
    set_code: str,
    rarity_code: str,
    data: dict,
) -> tuple[float, float | None]:
    """Resolve (sell_price, trend_price) for a new collection row."""
    if data.get("sell_price") is not None:
        sell = float(data["sell_price"])
        trend = data.get("trend_price")
        if trend is None:
            row = load_market_prices(session, [(set_code, rarity_code)]).get(
                (set_code, rarity_code)
            )
            trend = row.trend_price if row else None
        return sell, trend

    trend = data.get("trend_price")
    if trend is None:
        row = load_market_prices(session, [(set_code, rarity_code)]).get(
            (set_code, rarity_code)
        )
        trend = row.trend_price if row else None
    sell = float(trend) if trend is not None else 0.0
    return sell, trend


def add_collection_item(session: Session, user_id: int, data: dict) -> CollectionItem:
    rarity_code = normalize_rarity_code(data["rarity"])
    quantity = data.get("quantity", 1)
    set_code = data["set_code"].strip()
    sell_price, trend_price = _default_collection_prices(
        session,
        set_code=set_code,
        rarity_code=rarity_code,
        data=data,
    )
    item = CollectionItem(
        user_id=user_id,
        set_code=set_code,
        rarity_code=rarity_code,
        card_name=data.get("card_name"),
        expansion_code=data.get("expansion_code"),
        set_name=data.get("set_name"),
        quantity=quantity,
        trade_quantity=data.get("trade_quantity", 0),
        condition=data.get("condition"),
        edition=data.get("printing"),
        language=data.get("language"),
        price_bought=data.get("price_bought"),
        date_bought=data.get("date_bought"),
        avg_price=data.get("avg_price"),
        low_price=data.get("low_price"),
        trend_price=trend_price,
        sell_price=sell_price,
        notes=data.get("notes"),
        printing_id=session.execute(
            select(Printing.id)
            .where(Printing.set_code == set_code)
            .where(Printing.set_rarity_code == rarity_code)
            .limit(1)
        ).scalar(),
    )
    session.add(item)
    session.flush()

    if data.get("folder_allocations"):
        set_item_folder_allocations(
            session,
            user_id=user_id,
            item=item,
            allocations=data["folder_allocations"],
        )
    elif data.get("folder_id") is not None:
        folder_id = data["folder_id"]
        if folder_id is not None:
            folder = session.get(CollectionFolder, folder_id)
            if not folder or folder.user_id != user_id:
                raise ValueError("Folder not found")
        set_item_folder_allocations(
            session,
            user_id=user_id,
            item=item,
            allocations=[{"folder_id": folder_id, "quantity": quantity}],
        )
    else:
        set_item_folder_allocations(
            session,
            user_id=user_id,
            item=item,
            allocations=_default_folder_allocations(quantity),
        )

    session.commit()
    session.refresh(item)
    return item


def _reassign_collection_item_printing(
    session: Session,
    *,
    user_id: int,
    item: CollectionItem,
    set_code: str,
    rarity_code: str,
) -> None:
    """Move a collection row to another catalog printing (set code + rarity)."""
    printing = session.execute(
        select(Printing)
        .where(Printing.set_code == set_code)
        .where(Printing.set_rarity_code == rarity_code)
        .limit(1)
    ).scalars().first()
    if printing is None:
        raise ValueError(
            f"No catalog printing found for {set_code} ({rarity_display(rarity_code)})"
        )
    duplicate = session.execute(
        select(CollectionItem.id)
        .where(
            CollectionItem.user_id == user_id,
            CollectionItem.set_code == set_code,
            CollectionItem.rarity_code == rarity_code,
            CollectionItem.id != item.id,
        )
        .limit(1)
    ).scalar_one_or_none()
    if duplicate is not None:
        raise ValueError(
            f"You already have a collection row for {set_code} "
            f"({rarity_display(rarity_code)}); edit that row instead."
        )
    item.set_code = set_code
    item.rarity_code = rarity_code
    item.printing_id = printing.id
    item.set_name = printing.set_name
    if "-" in set_code:
        item.expansion_code = set_code.split("-", 1)[0]
    if printing.card is not None:
        item.card_name = printing.card.name


def update_collection_item(
    session: Session,
    *,
    user_id: int,
    item: CollectionItem,
    data: dict,
) -> CollectionItem:
    folder_allocations = data.pop("folder_allocations", None)
    if "printing" in data:
        data["edition"] = data.pop("printing")
    new_set_code = data.pop("set_code", None)
    new_rarity = data.pop("rarity", None)
    if new_set_code is not None or new_rarity is not None:
        set_code = (new_set_code or item.set_code).strip()
        rarity_code = (
            normalize_rarity_code(new_rarity)
            if new_rarity is not None
            else item.rarity_code
        )
        if set_code != item.set_code or rarity_code != item.rarity_code:
            _reassign_collection_item_printing(
                session,
                user_id=user_id,
                item=item,
                set_code=set_code,
                rarity_code=rarity_code,
            )
    old_quantity = item.quantity
    for field, value in data.items():
        setattr(item, field, value)
    if "quantity" in data and folder_allocations is None:
        if item.quantity != old_quantity:
            _reconcile_allocations_after_quantity_change(item)
    if folder_allocations is not None:
        set_item_folder_allocations(
            session,
            user_id=user_id,
            item=item,
            allocations=folder_allocations,
        )
    _ensure_default_allocations(item)
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
