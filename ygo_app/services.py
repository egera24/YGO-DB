from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, joinedload, load_only

import json
from collections import defaultdict
from datetime import date, datetime

from ygo_app.import_progress import ProgressThrottle
from ygo_app.models import (
    Card,
    CollectionFolder,
    CollectionItem,
    CollectionItemFolder,
    Deck,
    DeckCard,
    Printing,
    PrintingMarketPrice,
    RarityPriceRank,
    SearchPreset,
    TcgSet,
    User,
    UserCardTag,
    UserFavorite,
)
from ygo_app.card_filters import (
    link_markers_contain_all,
    mechanic_filter,
    parse_multi_param,
    types_overlap_filter,
)
from ygo_app.collection_identity import (
    COLLECTION_CONDITIONS,
    COLLECTION_EDITIONS,
    collection_item_key,
    find_collection_item_by_identity,
    normalize_collection_condition,
    normalize_collection_edition,
    normalize_collection_notes,
)
from ygo_app.cardmarket.market_prices import load_market_prices
from ygo_app.search_sort import (
    apply_collection_sort_joins,
    apply_sort_direction,
    build_card_search_order_by,
    build_collection_order_by,
)
from ygo_app.search_query import (
    SearchCompileContext,
    SearchQueryError,
    Term,
    compile_search_filter,
    text_search_filter,
)
from ygo_app.utils import normalize_rarity_code, rarity_display
from ygo_app.rarity_registry import rarity_match_variants, resolve_rarity
from ygo_app.trade_share import assign_unique_trade_slug, ensure_user_trade_slug
from ygo_app.yugipedia.set_chronology import set_abbr_from_code


class SearchPresetConflictError(Exception):
    """Raised when a preset name already exists for the user."""


def find_printing_for_rarity(
    session: Session, set_code: str, rarity_raw: str
) -> Printing | None:
    for variant in rarity_match_variants(rarity_raw):
        printing = session.execute(
            select(Printing)
            .where(Printing.set_code == set_code)
            .where(Printing.set_rarity_code == variant)
            .limit(1)
        ).scalars().first()
        if printing is not None:
            return printing
    return None


def resolve_collection_rarity(rarity_raw: str) -> tuple[str, str]:
    """Return (canonical normalized code, raw display) or raise ValueError."""
    text = (rarity_raw or "").strip()
    if not text:
        raise ValueError("Rarity is required")
    resolved = resolve_rarity(text)
    if resolved is None:
        raise ValueError(
            f"Unknown rarity '{rarity_display(normalize_rarity_code(text))}'"
        )
    return resolved.normalized_code, text


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
    for_trade_only: bool = False,
    tag: str | None = None,
    user_id: int | None = None,
    limit: int = 60,
    offset: int = 0,
    format_code: str | None = None,
    banlist_revision_id: int | None = None,
    banlist_status: str | None = None,
    genesys_point_list_id: int | None = None,
    points_min: int | None = None,
    points_max: int | None = None,
    sort: str = "name",
    sort_dir: str = "asc",
) -> tuple[list[Card], int]:
    search_columns = (
        Card.id,
        Card.passcode,
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
            stmt = stmt.where(Card.passcode == int(term))
            count_stmt = (
                select(func.count()).select_from(Card).where(Card.passcode == int(term))
            )
        else:
            search_ctx = SearchCompileContext(
                user_id=user_id,
                session=session,
                format_code=format_code,
                dialect=session.get_bind().dialect.name,
            )
            try:
                filt = text_search_filter(term, search_ctx)
            except SearchQueryError:
                filt = compile_search_filter(Term(term), search_ctx)
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

    mech_filt = mechanic_filter(mechanic)
    if mech_filt is not None:
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

    if for_trade_only and user_id is not None:
        trade_ids = session.execute(
            select(Printing.card_id)
            .join(
                CollectionItem,
                (CollectionItem.set_code == Printing.set_code)
                & (CollectionItem.rarity_code == Printing.set_rarity_code)
                & (CollectionItem.user_id == user_id),
            )
            .where(CollectionItem.trade_quantity > 0)
            .distinct()
        ).scalars().all()
        if not trade_ids:
            return [], 0
        stmt = stmt.where(Card.id.in_(trade_ids))
        count_stmt = count_stmt.where(Card.id.in_(trade_ids))
    elif for_trade_only:
        return [], 0

    if format_code:
        from ygo_app.formats.banlist import (
            db_statuses_for_effective_filters,
            partition_banlist_status_filters,
            parse_banlist_status_param,
            resolve_banlist_revision,
        )
        from ygo_app.formats.context import resolve_format_search_context
        from ygo_app.formats.pool import format_pool_legality_exists, warn_if_legality_table_empty
        from ygo_app.models import BanlistEntry, GenesysPointEntry

        ctx = resolve_format_search_context(
            session,
            format_code,
            genesys_point_list_id=genesys_point_list_id,
        )
        if ctx:
            if ctx.rules.pool_uses_legality_table:
                warn_if_legality_table_empty(session, ctx.rules)
                pool_filter = format_pool_legality_exists(ctx.rules.code)
                stmt = stmt.where(pool_filter)
                count_stmt = count_stmt.where(pool_filter)

            if ctx.rules.disallow_link:
                stmt = stmt.where(or_(Card.mechanic.is_(None), Card.mechanic != "Link"))
                count_stmt = count_stmt.where(
                    or_(Card.mechanic.is_(None), Card.mechanic != "Link")
                )
            if ctx.rules.disallow_pendulum:
                stmt = stmt.where(or_(Card.mechanic.is_(None), Card.mechanic != "Pendulum"))
                count_stmt = count_stmt.where(
                    or_(Card.mechanic.is_(None), Card.mechanic != "Pendulum")
                )

            if ctx.rules.uses_point_list and ctx.point_list and (
                points_min is not None or points_max is not None
            ):
                point_subq = select(GenesysPointEntry.card_id).where(
                    GenesysPointEntry.list_id == ctx.point_list.id,
                    GenesysPointEntry.card_id.is_not(None),
                )
                if points_min is not None:
                    point_subq = point_subq.where(GenesysPointEntry.points >= points_min)
                if points_max is not None:
                    point_subq = point_subq.where(GenesysPointEntry.points <= points_max)
                if points_min is not None and points_min <= 0:
                    stmt = stmt.where(
                        or_(Card.id.in_(point_subq), ~Card.id.in_(select(GenesysPointEntry.card_id).where(GenesysPointEntry.list_id == ctx.point_list.id)))
                    )
                    count_stmt = count_stmt.where(
                        or_(Card.id.in_(point_subq), ~Card.id.in_(select(GenesysPointEntry.card_id).where(GenesysPointEntry.list_id == ctx.point_list.id)))
                    )
                else:
                    stmt = stmt.where(Card.id.in_(point_subq))
                    count_stmt = count_stmt.where(Card.id.in_(point_subq))

            statuses = parse_banlist_status_param(banlist_status)
            if statuses:
                revision = resolve_banlist_revision(
                    session, ctx.rules, banlist_revision_id
                )
                if not revision:
                    return [], 0
                restricted_statuses, include_unlimited = partition_banlist_status_filters(
                    statuses
                )
                db_statuses = db_statuses_for_effective_filters(
                    restricted_statuses, ctx.rules
                )
                conditions = []
                if restricted_statuses:
                    if not db_statuses:
                        return [], 0
                    restricted = select(BanlistEntry.card_id).where(
                        BanlistEntry.revision_id == revision.id,
                        BanlistEntry.card_id.is_not(None),
                        BanlistEntry.status.in_(db_statuses),
                    )
                    conditions.append(Card.id.in_(restricted))
                if include_unlimited:
                    on_list = select(BanlistEntry.card_id).where(
                        BanlistEntry.revision_id == revision.id,
                        BanlistEntry.card_id.is_not(None),
                    )
                    conditions.append(~Card.id.in_(on_list))
                if conditions:
                    banlist_filter = or_(*conditions)
                    stmt = stmt.where(banlist_filter)
                    count_stmt = count_stmt.where(banlist_filter)

    total = session.execute(count_stmt).scalar() or 0
    dialect = session.get_bind().dialect.name
    order_by = build_card_search_order_by(
        sort, sort_dir, user_id, dialect=dialect
    )
    cards = (
        session.execute(stmt.order_by(*order_by).offset(offset).limit(limit))
        .scalars()
        .unique()
        .all()
    )
    return list(cards), int(total)


def enrich_cards_for_format(
    session: Session,
    cards: list[Card],
    *,
    format_code: str | None = None,
    ctx: object | None = None,
    banlist_revision_id: int | None = None,
    genesys_point_list_id: int | None = None,
    for_search: bool = False,
) -> dict[int, dict]:
    if not cards:
        return {}
    from ygo_app.formats.banlist import banlist_status_label
    from ygo_app.formats.context import resolve_format_enrich_context
    from ygo_app.formats.genesys import card_point_value
    from ygo_app.formats.pool import batch_card_legal_in_format

    if ctx is None:
        if not format_code:
            return {}
        ctx = resolve_format_enrich_context(
            session,
            format_code,
            banlist_revision_id=banlist_revision_id,
            genesys_point_list_id=genesys_point_list_id,
        )
    if not ctx:
        return {}

    legal_map: dict[int, bool] = {}
    if not for_search and (
        ctx.rules.pool_uses_legality_table or ctx.rules.pool_cutoff_date
    ):
        legal_map = batch_card_legal_in_format(
            session, [card.id for card in cards], ctx.rules
        )

    extras: dict[int, dict] = {}
    for card in cards:
        payload: dict = {}
        if ctx.banlist_map is not None:
            status = ctx.banlist_map.get(card.id)
            label = banlist_status_label(status, ctx.rules)
            if label is None and ctx.rules.banlist_mode != "none":
                label = "Unlimited"
            payload["banlist_status"] = label
        if ctx.rules.uses_point_list and ctx.points_map is not None:
            payload["genesys_points"] = card_point_value(card.id, ctx.points_map)
        if not for_search and (
            ctx.rules.pool_uses_legality_table or ctx.rules.pool_cutoff_date
        ):
            payload["format_legal"] = legal_map.get(card.id, False)
        extras[card.id] = payload
    return extras


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
    trade_map: dict[tuple[str, str], int] = {}
    collection_item_id_map: dict[tuple[str, str], int | None] = {}
    collection_variant_count_map: dict[tuple[str, str], int] = {}
    if user_id is not None:
        rows = session.execute(
            select(
                CollectionItem.set_code,
                CollectionItem.rarity_code,
                func.sum(CollectionItem.quantity),
                func.sum(CollectionItem.trade_quantity),
                func.count(CollectionItem.id),
                func.min(CollectionItem.id),
            )
            .join(
                Printing,
                (CollectionItem.set_code == Printing.set_code)
                & (CollectionItem.rarity_code == Printing.set_rarity_code),
            )
            .where(Printing.card_id == card_id, CollectionItem.user_id == user_id)
            .group_by(CollectionItem.set_code, CollectionItem.rarity_code)
        ).all()
        for set_code, rarity_code, qty, trade_qty, variant_count, item_id in rows:
            key = (set_code, rarity_code)
            owned_map[key] = int(qty or 0)
            trade_map[key] = int(trade_qty or 0)
            variant_count_int = int(variant_count or 0)
            collection_variant_count_map[key] = variant_count_int
            collection_item_id_map[key] = (
                int(item_id) if variant_count_int == 1 else None
            )

    for printing in card.printings:
        key = (printing.set_code, printing.set_rarity_code)
        printing.owned_quantity = owned_map.get(key, 0)
        printing.trade_quantity = trade_map.get(key, 0)
        printing.collection_item_id = collection_item_id_map.get(key)
        printing.collection_variant_count = collection_variant_count_map.get(key, 0)

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
    session: Session,
    *,
    user_id: int,
    folder_id: int,
    target_folder_id: int | None = None,
    remove_cards: bool = False,
) -> tuple[int, int, int, int]:
    folder = session.get(CollectionFolder, folder_id)
    if not folder or folder.user_id != user_id:
        raise ValueError("Folder not found")
    if remove_cards and target_folder_id is not None:
        raise ValueError(
            "Provide either remove_cards or target_folder_id, not both"
        )
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
    if allocations and not remove_cards and target_folder_id is None:
        raise ValueError(
            "target_folder_id is required when the folder still has cards"
        )
    if not remove_cards and target_folder_id is not None:
        if target_folder_id == folder_id:
            raise ValueError("target_folder_id must be a different folder")
        target = session.get(CollectionFolder, target_folder_id)
        if not target or target.user_id != user_id:
            raise ValueError("Folder not found")

    moved_allocations = 0
    moved_quantity = 0
    removed_allocations = 0
    removed_quantity = 0

    if remove_cards:
        items_to_delete: list[CollectionItem] = []
        for allocation in allocations:
            item = allocation.collection_item
            qty = int(allocation.quantity)
            removed_allocations += 1
            removed_quantity += qty
            if int(item.quantity or 0) > 0:
                item.quantity = max(0, int(item.quantity) - qty)
            else:
                item.trade_quantity = max(0, int(item.trade_quantity or 0) - qty)
            # Remove from the relationship so delete-orphan handles the row once;
            # avoids a double DELETE when the parent item is removed next.
            item.folder_allocations.remove(allocation)
            if int(item.quantity or 0) == 0 and int(item.trade_quantity or 0) == 0:
                items_to_delete.append(item)
        session.flush()
        for item in items_to_delete:
            session.delete(item)
    else:
        for allocation in allocations:
            item = allocation.collection_item
            moved_allocations += 1
            moved_quantity += int(allocation.quantity)
            existing_target = next(
                (
                    row
                    for row in item.folder_allocations
                    if row.folder_id == target_folder_id and row is not allocation
                ),
                None,
            )
            if existing_target:
                existing_target.quantity += allocation.quantity
                session.delete(allocation)
            else:
                allocation.folder_id = target_folder_id
    # Flush reassignments before deleting the folder so ON DELETE SET NULL
    # does not wipe the new folder_id.
    session.flush()
    session.delete(folder)
    session.commit()
    return moved_allocations, moved_quantity, removed_allocations, removed_quantity


def _folder_allocation_target(item: CollectionItem) -> int:
    keeper_qty = int(item.quantity or 0)
    if keeper_qty > 0:
        return keeper_qty
    return int(item.trade_quantity or 0)


def _validate_folder_allocations(
    session: Session,
    *,
    user_id: int,
    item: CollectionItem,
    allocations: list[dict],
) -> list[dict]:
    if not allocations:
        raise ValueError("At least one folder allocation is required")
    merged: dict[int, int] = {}
    for row in allocations:
        folder_id = row.get("folder_id")
        qty = int(row["quantity"])
        if qty < 1:
            raise ValueError("Allocation quantity must be at least 1")
        if folder_id is None:
            raise ValueError("Folder is required")
        folder = session.get(CollectionFolder, folder_id)
        if not folder or folder.user_id != user_id:
            raise ValueError("Folder not found")
        merged[folder_id] = merged.get(folder_id, 0) + qty
    total = sum(merged.values())
    target = _folder_allocation_target(item)
    if total != target:
        label = "quantity" if int(item.quantity or 0) > 0 else "trade quantity"
        raise ValueError(
            f"Folder allocations must sum to item {label} ({target}), got {total}"
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
    target = int(item.quantity or 0)
    if not allocations:
        if target > 0:
            raise ValueError("Folder is required")
        return
    if len(allocations) == 1:
        allocations[0].quantity = target
        return
    current_total = sum(int(row.quantity) for row in allocations)
    diff = target - current_total
    if diff == 0:
        return
    named = [row for row in allocations if row.folder_id is not None]
    if diff > 0 and named:
        named[0].quantity = int(named[0].quantity) + diff
        return
    if diff < 0:
        raise ValueError(
            "Reduce folder allocations before lowering total quantity"
        )
    raise ValueError("Folder is required")


def _ensure_default_allocations(item: CollectionItem) -> None:
    if item.folder_allocations:
        return
    if int(item.quantity or 0) > 0 or int(item.trade_quantity or 0) > 0:
        raise ValueError("Folder is required")



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


def _release_dates_by_set_codes(
    session: Session, set_codes: set[str] | list[str]
) -> dict[str, date]:
    from ygo_app.formats.pool import expansion_abbr_from_set_code

    set_code_to_abbr: dict[str, str] = {}
    abbrs: set[str] = set()
    for set_code in set_codes:
        abbr = expansion_abbr_from_set_code(set_code or "")
        if not abbr:
            continue
        set_code_to_abbr[set_code] = abbr
        abbrs.add(abbr)
    if not abbrs:
        return {}

    abbr_to_date = {
        abbr: release_date
        for abbr, release_date in session.execute(
            select(TcgSet.abbr, TcgSet.release_date).where(
                TcgSet.abbr.in_(abbrs),
                TcgSet.release_date.is_not(None),
            )
        ).all()
    }
    return {
        set_code: abbr_to_date[abbr]
        for set_code, abbr in set_code_to_abbr.items()
        if abbr in abbr_to_date
    }


def _collection_item_row(
    item: CollectionItem,
    *,
    set_code_fallback: dict[str, Card | None] | None = None,
    folder_filter: str | None = None,
    market_row: PrintingMarketPrice | None = None,
    release_date_map: dict[str, date] | None = None,
) -> dict:
    card = _card_for_collection_item(item, set_code_fallback=set_code_fallback)
    linked = item.linked_printing
    resolved = resolve_rarity(item.rarity_code)
    if resolved is not None:
        rarity_name = resolved.name
    else:
        rarity_name = linked.set_rarity if linked is not None else None
    row = {c.name: getattr(item, c.name) for c in CollectionItem.__table__.columns}
    row["condition"] = normalize_collection_condition(row.get("condition"))
    row["edition"] = normalize_collection_edition(row.get("edition"))
    row["printing"] = row["edition"]
    if market_row is not None:
        row["low_price"] = market_row.low_price
        row["avg_price"] = market_row.avg_price
        row["trend_price"] = market_row.trend_price
    else:
        row["low_price"] = None
        row["avg_price"] = None
        row["trend_price"] = None
    folders = _folder_allocations_for_row(item)
    display_quantity = item.quantity
    if folder_filter == NO_FOLDER:
        alloc = next((f for f in folders if f["folder_id"] is None), None)
        display_quantity = alloc["quantity"] if alloc else 0
    elif folder_filter and folder_filter != NO_FOLDER:
        folder_id = int(folder_filter)
        alloc = next((f for f in folders if f["folder_id"] == folder_id), None)
        display_quantity = alloc["quantity"] if alloc else 0
    display_card_name = item.card_name or (card.name if card else None)
    return {
        **row,
        "card_name": display_card_name,
        "quantity": display_quantity,
        "card_id": card.id if card else None,
        "image_url_small": card.image_url_small if card else None,
        "rarity_display": rarity_display(item.rarity_code),
        "rarity_name": rarity_name,
        "folders": folders,
        "release_date": release_date_map.get(item.set_code) if release_date_map else None,
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


def _scoped_collection_quantity(item: CollectionItem, folder_filter: str | None) -> int:
    folders = _folder_allocations_for_row(item)
    if folder_filter == NO_FOLDER:
        alloc = next((f for f in folders if f["folder_id"] is None), None)
        return int(alloc["quantity"]) if alloc else 0
    if folder_filter and folder_filter != NO_FOLDER:
        folder_id = int(folder_filter)
        alloc = next((f for f in folders if f["folder_id"] == folder_id), None)
        return int(alloc["quantity"]) if alloc else 0
    return int(item.quantity)


def _apply_collection_item_filters(
    stmt,
    *,
    user_id: int,
    q: str | None = None,
    card_name: str | None = None,
    set_code: str | None = None,
    set_name: str | None = None,
    rarity: str | None = None,
    edition: str | None = None,
    condition: str | None = None,
    folder: str | None = None,
):
    stmt = stmt.where(CollectionItem.user_id == user_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                CollectionItem.card_name.ilike(like),
                CollectionItem.set_code.ilike(like),
                CollectionItem.set_name.ilike(like),
            )
        )
    if card_name:
        stmt = stmt.where(CollectionItem.card_name.ilike(f"%{card_name.strip()}%"))
    if set_code:
        stmt = stmt.where(CollectionItem.set_code.ilike(f"%{set_code.strip()}%"))
    if set_name:
        stmt = stmt.where(CollectionItem.set_name.ilike(f"%{set_name.strip()}%"))
    if rarity:
        stmt = stmt.where(CollectionItem.rarity_code == rarity.strip())
    if edition:
        norm = normalize_collection_edition(edition)
        if norm:
            stmt = stmt.where(CollectionItem.edition == norm)
    if condition:
        norm = normalize_collection_condition(condition)
        if norm:
            stmt = stmt.where(CollectionItem.condition == norm)
    return _apply_collection_folder_filter(stmt, folder)


def _resolve_collection_folder_label(
    session: Session, *, user_id: int, folder: str | None
) -> str:
    if not folder:
        return "All"
    if folder == NO_FOLDER:
        return "No Folder"
    row = session.execute(
        select(CollectionFolder.name).where(
            CollectionFolder.id == int(folder),
            CollectionFolder.user_id == user_id,
        )
    ).scalar_one_or_none()
    return row or f"Folder {folder}"


def _collection_filter_rarities(session: Session, filtered_ids) -> list[dict]:
    rarity_codes = session.execute(
        select(CollectionItem.rarity_code)
        .where(CollectionItem.id.in_(filtered_ids))
        .where(
            CollectionItem.rarity_code.isnot(None),
            CollectionItem.rarity_code != "",
        )
        .distinct()
    ).scalars().all()

    seen: set[str] = set()
    rarities: list[dict] = []
    for code in rarity_codes:
        resolved = resolve_rarity(code)
        key = resolved.name if resolved else code
        if key in seen:
            continue
        seen.add(key)
        rarities.append(
            {
                "rarity_code": code,
                "rarity_name": resolved.name if resolved else None,
            }
        )
    rarities.sort(key=lambda row: (row["rarity_name"] or row["rarity_code"]).lower())
    return rarities


def _collection_filtered_item_ids(
    *,
    user_id: int,
    q: str | None = None,
    card_name: str | None = None,
    set_code: str | None = None,
    set_name: str | None = None,
    rarity: str | None = None,
    edition: str | None = None,
    condition: str | None = None,
    folder: str | None = None,
    exclude: frozenset[str] = frozenset(),
):
    stmt = select(CollectionItem)
    stmt = _apply_collection_item_filters(
        stmt,
        user_id=user_id,
        q=q,
        card_name=card_name,
        set_code=set_code,
        set_name=set_name,
        rarity=None if "rarity" in exclude else rarity,
        edition=None if "edition" in exclude else edition,
        condition=None if "condition" in exclude else condition,
        folder=folder,
    )
    return stmt.with_only_columns(CollectionItem.id)


def collection_filter_options(
    session: Session,
    *,
    user_id: int,
    q: str | None = None,
    card_name: str | None = None,
    set_code: str | None = None,
    set_name: str | None = None,
    rarity: str | None = None,
    edition: str | None = None,
    condition: str | None = None,
    folder: str | None = None,
) -> dict:
    filter_kwargs = {
        "user_id": user_id,
        "q": q,
        "card_name": card_name,
        "set_code": set_code,
        "set_name": set_name,
        "rarity": rarity,
        "edition": edition,
        "condition": condition,
        "folder": folder,
    }

    rarity_ids = _collection_filtered_item_ids(**filter_kwargs, exclude=frozenset({"rarity"}))
    edition_ids = _collection_filtered_item_ids(**filter_kwargs, exclude=frozenset({"edition"}))
    condition_ids = _collection_filtered_item_ids(**filter_kwargs, exclude=frozenset({"condition"}))

    editions = session.execute(
        select(CollectionItem.edition)
        .where(CollectionItem.id.in_(edition_ids))
        .where(CollectionItem.edition.isnot(None), CollectionItem.edition != "")
        .distinct()
        .order_by(CollectionItem.edition)
    ).scalars().all()

    conditions = session.execute(
        select(CollectionItem.condition)
        .where(CollectionItem.id.in_(condition_ids))
        .where(CollectionItem.condition.isnot(None), CollectionItem.condition != "")
        .distinct()
        .order_by(CollectionItem.condition)
    ).scalars().all()

    normalized_editions = sorted(
        {normalize_collection_edition(e) for e in editions if normalize_collection_edition(e)},
        key=str.lower,
    )
    normalized_conditions = sorted(
        {normalize_collection_condition(c) for c in conditions if normalize_collection_condition(c)},
        key=str.lower,
    )

    return {
        "rarities": _collection_filter_rarities(session, rarity_ids),
        "editions": normalized_editions,
        "conditions": normalized_conditions,
    }


def collection_suggestions(
    session: Session,
    *,
    user_id: int,
    field: str,
    q: str | None = None,
    limit: int = 20,
    q_filter: str | None = None,
    card_name: str | None = None,
    set_code: str | None = None,
    set_name: str | None = None,
    rarity: str | None = None,
    edition: str | None = None,
    condition: str | None = None,
    folder: str | None = None,
) -> list[str]:
    column_map = {
        "card_name": CollectionItem.card_name,
        "set_code": CollectionItem.set_code,
        "set_name": CollectionItem.set_name,
    }
    column = column_map.get(field)
    if column is None:
        return []

    stmt = select(CollectionItem)
    stmt = _apply_collection_item_filters(
        stmt,
        user_id=user_id,
        q=q_filter,
        card_name=card_name,
        set_code=set_code,
        set_name=set_name,
        rarity=rarity,
        edition=edition,
        condition=condition,
        folder=folder,
    )
    stmt = stmt.where(column.isnot(None), column != "")
    if q and q.strip():
        stmt = stmt.where(column.ilike(f"%{q.strip()}%"))

    rows = session.execute(
        select(column)
        .where(CollectionItem.id.in_(stmt.with_only_columns(CollectionItem.id)))
        .where(column.isnot(None), column != "")
        .distinct()
        .order_by(column)
        .limit(max(1, min(limit, 50)))
    ).scalars().all()
    return [str(value).strip() for value in rows if str(value).strip()]


def collection_detail_stats(
    session: Session,
    *,
    user_id: int,
    folder: str | None = None,
) -> dict:
    stmt = select(CollectionItem).where(CollectionItem.user_id == user_id)
    stmt = _apply_collection_folder_filter(stmt, folder)
    items = (
        session.execute(
            stmt.options(
                joinedload(CollectionItem.linked_printing).joinedload(Printing.card),
                joinedload(CollectionItem.folder_allocations).joinedload(
                    CollectionItemFolder.folder
                ),
            )
        )
        .unique()
        .scalars()
        .all()
    )

    missing_codes = {
        item.set_code for item in items if _card_for_collection_item(item) is None
    }
    fallback_map = _cards_by_set_codes(session, missing_codes)
    market_keys = [(item.set_code, item.rarity_code) for item in items]
    market_map = load_market_prices(session, market_keys)
    release_date_map = _release_dates_by_set_codes(session, {item.set_code for item in items})

    unique_printings = 0
    total_quantity = 0
    sum_low = 0.0
    sum_avg = 0.0
    sum_trend = 0.0
    has_low = False
    has_avg = False
    has_trend = False
    max_item: CollectionItem | None = None
    max_row: dict | None = None
    max_trend: float | None = None

    for item in items:
        qty = _scoped_collection_quantity(item, folder)
        if qty <= 0:
            continue
        unique_printings += 1
        total_quantity += qty

        market_row = market_map.get((item.set_code, item.rarity_code))
        low = market_row.low_price if market_row else None
        avg = market_row.avg_price if market_row else None
        trend = market_row.trend_price if market_row else None

        if low is not None:
            has_low = True
            sum_low += float(low) * qty
        if avg is not None:
            has_avg = True
            sum_avg += float(avg) * qty
        if trend is not None:
            has_trend = True
            sum_trend += float(trend) * qty

        trend_val = float(trend) if trend is not None else None
        if trend_val is not None:
            replace = False
            if max_item is None:
                replace = True
            elif max_trend is None or trend_val > max_trend:
                replace = True
            elif trend_val == max_trend:
                max_qty = max_row["quantity"] if max_row else 0
                max_name = (max_row.get("card_name") or "").lower() if max_row else ""
                row = _collection_item_row(
                    item,
                    set_code_fallback=fallback_map,
                    folder_filter=folder,
                    market_row=market_row,
                    release_date_map=release_date_map,
                )
                if qty > max_qty or (
                    qty == max_qty
                    and (row.get("card_name") or "").lower() < max_name
                ):
                    replace = True
            if replace:
                max_item = item
                max_trend = trend_val
                max_row = _collection_item_row(
                    item,
                    set_code_fallback=fallback_map,
                    folder_filter=folder,
                    market_row=market_row,
                    release_date_map=release_date_map,
                )

    return {
        "folder": folder,
        "folder_label": _resolve_collection_folder_label(
            session, user_id=user_id, folder=folder
        ),
        "unique_printings": unique_printings,
        "total_quantity": total_quantity,
        "sum_low_price": sum_low if has_low else None,
        "sum_avg_price": sum_avg if has_avg else None,
        "sum_trend_price": sum_trend if has_trend else None,
        "max_value_item": max_row,
    }


def list_collection(
    session: Session,
    *,
    user_id: int,
    q: str | None = None,
    card_name: str | None = None,
    set_code: str | None = None,
    set_name: str | None = None,
    rarity: str | None = None,
    edition: str | None = None,
    condition: str | None = None,
    folder: str | None = None,
    sort: str = "set_code",
    sort_dir: str = "asc",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    stmt = select(CollectionItem)
    stmt = _apply_collection_item_filters(
        stmt,
        user_id=user_id,
        q=q,
        card_name=card_name,
        set_code=set_code,
        set_name=set_name,
        rarity=rarity,
        edition=edition,
        condition=condition,
        folder=folder,
    )

    total = session.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar() or 0

    dialect = session.get_bind().dialect.name
    stmt = apply_collection_sort_joins(stmt, sort, dialect=dialect)
    order_by = build_collection_order_by(sort, sort_dir)

    items = (
        session.execute(
            stmt.options(
                joinedload(CollectionItem.linked_printing).joinedload(Printing.card),
                joinedload(CollectionItem.folder_allocations).joinedload(
                    CollectionItemFolder.folder
                ),
            )
            .order_by(*order_by)
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

    market_keys = [(item.set_code, item.rarity_code) for item in items]
    market_map = load_market_prices(session, market_keys)
    release_date_map = _release_dates_by_set_codes(session, {item.set_code for item in items})

    results = [
        _collection_item_row(
            item,
            set_code_fallback=fallback_map,
            folder_filter=folder,
            market_row=market_map.get((item.set_code, item.rarity_code)),
            release_date_map=release_date_map,
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
            key=lambda t: (_deck_zone_sort_key(t[0].zone), t[0].sort_order)
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
    *,
    validation: dict | None = None,
) -> dict:
    card_count = counts.get("main", 0) + counts.get("extra", 0) + counts.get("side", 0)
    payload = {
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
        "format_code": deck.format_code,
        "banlist_revision_id": deck.banlist_revision_id,
        "genesys_point_list_id": deck.genesys_point_list_id,
    }
    if validation is not None:
        payload["validation"] = validation
    return payload


def validate_deck_for_api(session: Session, deck: Deck) -> dict:
    from ygo_app.formats.validate import validate_deck

    return validate_deck(session, deck).to_dict()


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


VALID_DECK_ZONES = frozenset({"main", "extra", "side"})


def _apply_deck_settings(session: Session, deck: Deck, updates: dict) -> None:
    if "name" in updates and updates["name"] is not None:
        deck.name = updates["name"].strip()
    if "description" in updates:
        deck.description = updates["description"]
    if "preview_card_id" in updates:
        preview_card_id = updates["preview_card_id"]
        if preview_card_id is not None:
            in_deck = session.execute(
                select(DeckCard.id)
                .where(
                    DeckCard.deck_id == deck.id,
                    DeckCard.card_id == preview_card_id,
                )
                .limit(1)
            ).scalar_one_or_none()
            if not in_deck:
                raise ValueError("Preview card must be in the deck")
        deck.preview_card_id = preview_card_id
    if "format_code" in updates and updates["format_code"] is not None:
        deck.format_code = updates["format_code"]
    if "banlist_revision_id" in updates:
        deck.banlist_revision_id = updates["banlist_revision_id"]
    if "genesys_point_list_id" in updates:
        deck.genesys_point_list_id = updates["genesys_point_list_id"]


def reconcile_deck_cards(session: Session, deck_id: int, cards: list[dict]) -> None:
    existing_rows = session.execute(
        select(DeckCard).where(DeckCard.deck_id == deck_id)
    ).scalars().all()
    old_card_ids = {row.card_id for row in existing_rows}

    new_entries: list[dict] = []
    zone_counters = {"main": 0, "extra": 0, "side": 0}
    for item in cards:
        zone = item.get("zone", "main")
        if zone not in VALID_DECK_ZONES:
            continue
        card_id = int(item["card_id"])
        quantity = int(item.get("quantity", 1))
        if quantity <= 0:
            continue
        if session.get(Card, card_id) is None:
            continue
        for _ in range(quantity):
            new_entries.append(
                {
                    "card_id": card_id,
                    "zone": zone,
                    "sort_order": zone_counters[zone],
                }
            )
            zone_counters[zone] += 1

    new_card_ids = {entry["card_id"] for entry in new_entries}
    removed_card_ids = old_card_ids - new_card_ids

    for row in existing_rows:
        session.delete(row)

    for entry in new_entries:
        session.add(
            DeckCard(
                deck_id=deck_id,
                card_id=entry["card_id"],
                zone=entry["zone"],
                quantity=1,
                sort_order=entry["sort_order"],
            )
        )

    session.flush()

    for card_id in removed_card_ids:
        clear_deck_preview_if_removed(session, deck_id, card_id)


def apply_deck_save(session: Session, deck: Deck, body: dict) -> None:
    reconcile_deck_cards(session, deck.id, body.get("cards") or [])
    session.flush()
    settings = {
        "name": body.get("name"),
        "description": body.get("description"),
        "preview_card_id": body.get("preview_card_id"),
        "format_code": body.get("format_code"),
        "banlist_revision_id": body.get("banlist_revision_id"),
        "genesys_point_list_id": body.get("genesys_point_list_id"),
    }
    _apply_deck_settings(session, deck, settings)
    deck.updated_at = datetime.utcnow()


def update_deck(session: Session, deck: Deck, updates: dict) -> Deck:
    _apply_deck_settings(session, deck, updates)
    deck.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(deck)
    return deck


def add_collection_item(session: Session, user_id: int, data: dict) -> CollectionItem:
    rarity_code, rarity_raw = resolve_collection_rarity(data["rarity"])
    quantity = data.get("quantity", 1)
    set_code = data["set_code"].strip()
    edition = normalize_collection_edition(data.get("printing"))
    condition = normalize_collection_condition(data.get("condition"))
    trade_quantity = data.get("trade_quantity", 0)
    sell_price = (
        float(data["sell_price"]) if data.get("sell_price") is not None else None
    )
    notes = normalize_collection_notes(data.get("notes"))
    folder_allocations = data.get("folder_allocations")
    folder_id = data.get("folder_id")

    needs_folder = int(quantity or 0) > 0 or int(trade_quantity or 0) > 0
    if needs_folder and not folder_allocations and folder_id is None:
        raise ValueError("Folder is required")

    existing = find_collection_item_by_identity(
        session,
        user_id=user_id,
        set_code=set_code,
        rarity_code=rarity_code,
        edition=edition,
        condition=condition,
    )
    if existing is not None:
        existing.quantity += quantity
        existing.trade_quantity += trade_quantity
        if sell_price is not None:
            existing.sell_price = sell_price
        if folder_allocations:
            # Rebuild allocations from request, scaled to total item quantity.
            set_item_folder_allocations(
                session,
                user_id=user_id,
                item=existing,
                allocations=folder_allocations,
            )
        elif folder_id is not None:
            folder = session.get(CollectionFolder, folder_id)
            if not folder or folder.user_id != user_id:
                raise ValueError("Folder not found")
            no_folder_qty = sum(
                int(row.quantity)
                for row in existing.folder_allocations
                if row.folder_id is None
            )
            allocs = [
                {"folder_id": row.folder_id, "quantity": int(row.quantity)}
                for row in existing.folder_allocations
                if row.folder_id is not None
            ]
            add_qty = quantity + no_folder_qty
            if add_qty > 0:
                matched = next(
                    (row for row in allocs if row["folder_id"] == folder_id),
                    None,
                )
                if matched is not None:
                    matched["quantity"] += add_qty
                else:
                    allocs.append({"folder_id": folder_id, "quantity": add_qty})
                set_item_folder_allocations(
                    session,
                    user_id=user_id,
                    item=existing,
                    allocations=allocs,
                )
            else:
                _reconcile_allocations_after_quantity_change(existing)
        elif quantity > 0:
            raise ValueError("Folder is required")
        else:
            _reconcile_allocations_after_quantity_change(existing)
        session.commit()
        session.refresh(existing)
        return existing

    item = CollectionItem(
        user_id=user_id,
        set_code=set_code,
        rarity_code=rarity_code,
        card_name=data.get("card_name"),
        expansion_code=data.get("expansion_code"),
        set_name=data.get("set_name"),
        quantity=quantity,
        trade_quantity=trade_quantity,
        condition=condition,
        edition=edition,
        language=data.get("language"),
        price_bought=data.get("price_bought"),
        date_bought=data.get("date_bought"),
        sell_price=sell_price,
        notes=notes,
        printing_id=None,
    )
    printing = find_printing_for_rarity(session, set_code, rarity_raw)
    if printing is not None:
        item.printing_id = printing.id
    session.add(item)
    session.flush()

    if item.printing_id:
        printing = session.get(Printing, item.printing_id)
        if printing is not None:
            if not item.set_name:
                item.set_name = printing.set_name
            if not item.expansion_code and "-" in set_code:
                item.expansion_code = set_code.split("-", 1)[0]
            if not item.card_name:
                card = session.get(Card, printing.card_id)
                if card is not None:
                    item.card_name = card.name

    if folder_allocations:
        set_item_folder_allocations(
            session,
            user_id=user_id,
            item=item,
            allocations=folder_allocations,
        )
    elif folder_id is not None:
        folder = session.get(CollectionFolder, folder_id)
        if not folder or folder.user_id != user_id:
            raise ValueError("Folder not found")
        alloc_qty = quantity if quantity > 0 else trade_quantity
        set_item_folder_allocations(
            session,
            user_id=user_id,
            item=item,
            allocations=[{"folder_id": folder_id, "quantity": alloc_qty}],
        )
    elif needs_folder:
        raise ValueError("Folder is required")

    session.commit()
    session.refresh(item)
    return item


def _reassign_collection_item_printing(
    session: Session,
    *,
    user_id: int,
    item: CollectionItem,
    set_code: str,
    rarity_raw: str,
    rarity_code: str,
) -> None:
    """Move a collection row to another catalog printing (set code + rarity)."""
    printing = find_printing_for_rarity(session, set_code, rarity_raw)
    if printing is None:
        resolved = resolve_rarity(rarity_raw)
        label = rarity_display(rarity_code)
        if resolved is not None:
            label = f"{label} ({resolved.name})"
        raise ValueError(
            f"No catalog printing found for {set_code} ({label})"
        )
    duplicate = find_collection_item_by_identity(
        session,
        user_id=user_id,
        set_code=set_code,
        rarity_code=rarity_code,
        edition=item.edition,
        condition=item.condition,
        exclude_item_id=item.id,
    )
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
        if new_rarity is not None:
            rarity_code, rarity_raw = resolve_collection_rarity(new_rarity)
        else:
            rarity_code = item.rarity_code
            rarity_raw = rarity_display(item.rarity_code)
        if set_code != item.set_code or rarity_code != item.rarity_code:
            _reassign_collection_item_printing(
                session,
                user_id=user_id,
                item=item,
                set_code=set_code,
                rarity_raw=rarity_raw,
                rarity_code=rarity_code,
            )
    old_quantity = item.quantity
    if "edition" in data:
        data["edition"] = normalize_collection_edition(data["edition"])
    if "condition" in data:
        data["condition"] = normalize_collection_condition(data["condition"])
    if "notes" in data:
        data["notes"] = normalize_collection_notes(data["notes"])
    for field, value in data.items():
        setattr(item, field, value)
    if any(field in data for field in ("edition", "condition")):
        duplicate = find_collection_item_by_identity(
            session,
            user_id=user_id,
            set_code=item.set_code,
            rarity_code=item.rarity_code,
            edition=item.edition,
            condition=item.condition,
            exclude_item_id=item.id,
        )
        if duplicate is not None:
            raise ValueError(
                f"You already have a collection row for {item.set_code} "
                f"({rarity_display(item.rarity_code)}) with this edition and condition."
            )
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


PUBLIC_TRADE_SORT_FIELDS = frozenset(
    {"set_code", "card_name", "trade_quantity", "sell_price", "condition"}
)


def _expansion_code_for_item(set_code: str, expansion_code: str | None = None) -> str:
    for candidate in (expansion_code, set_code):
        text = (candidate or "").strip()
        if not text:
            continue
        if "-" in text:
            return text.split("-", 1)[0]
        return text
    return ""


def _apply_public_trade_expansion_filter(stmt, expansion: str):
    expansion = expansion.strip()
    if not expansion:
        return stmt
    return stmt.where(
        or_(
            CollectionItem.expansion_code == expansion,
            CollectionItem.set_code.ilike(f"{expansion}-%"),
            CollectionItem.set_code == expansion,
        )
    )


def _apply_public_trade_rarity_filter(stmt, rarity: str):
    rarity = rarity.strip()
    if not rarity:
        return stmt
    variants = rarity_match_variants(rarity)
    if not variants:
        return stmt
    return stmt.where(CollectionItem.rarity_code.in_(variants))


def _build_public_trade_order_by(sort: str, sort_dir: str) -> list:
    field = sort if sort in PUBLIC_TRADE_SORT_FIELDS else "set_code"
    direction = sort_dir if sort_dir in ("asc", "desc") else "asc"
    tie = apply_sort_direction(CollectionItem.id, direction)
    columns = {
        "set_code": CollectionItem.set_code,
        "card_name": CollectionItem.card_name,
        "trade_quantity": CollectionItem.trade_quantity,
        "sell_price": CollectionItem.sell_price,
        "condition": CollectionItem.condition,
    }
    order_col = columns.get(field, CollectionItem.set_code)
    return [apply_sort_direction(order_col, direction, nulls=True), tie]


def get_user_by_trade_slug(session: Session, slug: str) -> User | None:
    return session.execute(
        select(User).where(User.trade_share_slug == slug)
    ).scalar_one_or_none()


def get_trade_settings(session: Session, user_id: int) -> dict:
    user = session.get(User, user_id)
    if user is None:
        raise ValueError("User not found")
    if not user.trade_share_slug:
        ensure_user_trade_slug(session, user)
        session.commit()
        session.refresh(user)
    return {
        "slug": user.trade_share_slug,
        "display_name": user.trade_display_name,
    }


def update_trade_settings(
    session: Session,
    user_id: int,
    *,
    slug: str | None = None,
    display_name: str | None = None,
) -> dict:
    user = session.get(User, user_id)
    if user is None:
        raise ValueError("User not found")
    ensure_user_trade_slug(session, user)
    if slug is not None:
        assign_unique_trade_slug(session, user, slug)
    if display_name is not None:
        user.trade_display_name = display_name.strip() or None
    session.commit()
    session.refresh(user)
    return {
        "slug": user.trade_share_slug,
        "display_name": user.trade_display_name,
    }


def _public_trade_sell_price(
    item: CollectionItem,
    market_row: PrintingMarketPrice | None,
) -> float | None:
    if item.sell_price is not None:
        return float(item.sell_price)
    if market_row is not None and market_row.trend_price is not None:
        return float(market_row.trend_price)
    return None


def _public_trade_item_row(
    item: CollectionItem,
    *,
    set_code_fallback: dict | None = None,
    market_row: PrintingMarketPrice | None = None,
) -> dict:
    card = _card_for_collection_item(item, set_code_fallback=set_code_fallback)
    linked = item.linked_printing
    resolved = resolve_rarity(item.rarity_code)
    if resolved is not None:
        rarity_name = resolved.name
    else:
        rarity_name = linked.set_rarity if linked is not None else None
    return {
        "item_id": item.id,
        "card_name": item.card_name or (card.name if card else None),
        "set_code": item.set_code,
        "set_name": item.set_name,
        "rarity_code": item.rarity_code,
        "rarity_display": rarity_display(item.rarity_code),
        "rarity_name": rarity_name,
        "edition": normalize_collection_edition(item.edition),
        "condition": normalize_collection_condition(item.condition),
        "trade_quantity": item.trade_quantity,
        "sell_price": _public_trade_sell_price(item, market_row),
        "image_url_small": card.image_url_small if card else None,
    }


def list_public_trade_items(
    session: Session,
    *,
    user_id: int,
    q: str | None = None,
    set_code: str | None = None,
    rarity: str | None = None,
    sort: str = "set_code",
    sort_dir: str = "asc",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    stmt = select(CollectionItem).where(
        CollectionItem.user_id == user_id,
        CollectionItem.trade_quantity > 0,
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                CollectionItem.card_name.ilike(like),
                CollectionItem.set_code.ilike(like),
                CollectionItem.set_name.ilike(like),
            )
        )
    if set_code:
        stmt = _apply_public_trade_expansion_filter(stmt, set_code)
    if rarity:
        stmt = _apply_public_trade_rarity_filter(stmt, rarity)

    total = session.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar() or 0

    dialect = session.get_bind().dialect.name
    if sort in {"passcode", "release_date", "folder_name"}:
        sort = "set_code"
    stmt = apply_collection_sort_joins(stmt, sort, dialect=dialect)
    order_by = _build_public_trade_order_by(sort, sort_dir)

    items = (
        session.execute(
            stmt.options(
                joinedload(CollectionItem.linked_printing).joinedload(Printing.card),
            )
            .order_by(*order_by)
            .offset(offset)
            .limit(limit)
        )
        .unique()
        .scalars()
        .all()
    )

    missing_codes = {
        item.set_code for item in items if _card_for_collection_item(item) is None
    }
    fallback_map = _cards_by_set_codes(session, missing_codes)
    market_map = load_market_prices(
        session, [(item.set_code, item.rarity_code) for item in items]
    )

    results = [
        _public_trade_item_row(
            item,
            set_code_fallback=fallback_map,
            market_row=market_map.get((item.set_code, item.rarity_code)),
        )
        for item in items
    ]
    return results, int(total)


def public_trade_filters(session: Session, *, user_id: int) -> dict:
    rows = session.execute(
        select(
            CollectionItem.set_code,
            CollectionItem.expansion_code,
            CollectionItem.set_name,
        )
        .where(
            CollectionItem.user_id == user_id,
            CollectionItem.trade_quantity > 0,
        )
        .distinct()
    ).all()

    expansion_names: dict[str, str | None] = {}
    for set_code, expansion_code, set_name in rows:
        code = _expansion_code_for_item(set_code, expansion_code)
        if not code:
            continue
        if code not in expansion_names:
            expansion_names[code] = (set_name or "").strip() or None
        elif not expansion_names[code] and set_name:
            expansion_names[code] = set_name.strip()

    missing_names = [code for code, name in expansion_names.items() if not name]
    if missing_names:
        tcg_rows = session.execute(
            select(TcgSet).where(TcgSet.abbr.in_(missing_names))
        ).scalars().all()
        for tcg_set in tcg_rows:
            if tcg_set.abbr in expansion_names and not expansion_names[tcg_set.abbr]:
                expansion_names[tcg_set.abbr] = tcg_set.name

    sets = sorted(
        [
            {"expansion_code": code, "set_name": name}
            for code, name in expansion_names.items()
        ],
        key=lambda row: (row["set_name"] or row["expansion_code"]).lower(),
    )

    conditions = session.execute(
        select(CollectionItem.condition)
        .where(
            CollectionItem.user_id == user_id,
            CollectionItem.trade_quantity > 0,
            CollectionItem.condition.isnot(None),
            CollectionItem.condition != "",
        )
        .distinct()
        .order_by(CollectionItem.condition)
    ).scalars().all()

    rarity_codes = session.execute(
        select(CollectionItem.rarity_code)
        .where(
            CollectionItem.user_id == user_id,
            CollectionItem.trade_quantity > 0,
            CollectionItem.rarity_code.isnot(None),
            CollectionItem.rarity_code != "",
        )
        .distinct()
    ).scalars().all()

    seen_rarities: set[str] = set()
    rarities: list[dict] = []
    for code in rarity_codes:
        resolved = resolve_rarity(code)
        key = resolved.name if resolved else code
        if key in seen_rarities:
            continue
        seen_rarities.add(key)
        rarities.append(
            {
                "rarity_code": code,
                "rarity_name": resolved.name if resolved else None,
            }
        )
    rarities.sort(key=lambda row: (row["rarity_name"] or row["rarity_code"]).lower())

    return {
        "sets": sets,
        "conditions": list(conditions),
        "rarities": rarities,
    }


def validate_and_build_trade_order(
    session: Session,
    owner_id: int,
    lines: list[dict],
) -> list[dict]:
    if not lines:
        raise ValueError("Order must include at least one line")

    item_ids = [line["item_id"] for line in lines]
    items = session.execute(
        select(CollectionItem)
        .options(joinedload(CollectionItem.linked_printing))
        .where(
            CollectionItem.user_id == owner_id,
            CollectionItem.id.in_(item_ids),
            CollectionItem.trade_quantity > 0,
        )
    ).unique().scalars().all()
    by_id = {item.id: item for item in items}
    market_map = load_market_prices(
        session, [(item.set_code, item.rarity_code) for item in items]
    )

    built: list[dict] = []
    for line in lines:
        item_id = line["item_id"]
        item = by_id.get(item_id)
        if item is None:
            raise ValueError(f"Invalid item in order: {item_id}")
        qty = line["quantity"]
        if qty > item.trade_quantity:
            raise ValueError(
                f"Requested quantity exceeds trade quantity for item {item_id}"
            )
        market_row = market_map.get((item.set_code, item.rarity_code))
        built.append(
            {
                "item_id": item_id,
                "quantity": qty,
                "comment": line.get("comment"),
                "offer_price": line.get("offer_price"),
                "card_name": item.card_name,
                "set_code": item.set_code,
                "set_name": item.set_name,
                "rarity_code": item.rarity_code,
                "rarity_display": rarity_display(item.rarity_code),
                "condition": normalize_collection_condition(item.condition),
                "list_price": _public_trade_sell_price(item, market_row),
            }
        )
    return built


BULK_DEFAULT_CONDITION = "NearMint"
BULK_DEFAULT_EDITION = "1st Edition"
BULK_DEFAULT_LANGUAGE = "English"
BULK_GRID_MAX_CHANGES = 500


def _bulk_rarity_sort_map(session: Session) -> dict[str, int]:
    rows = session.scalars(
        select(RarityPriceRank).order_by(RarityPriceRank.sort_order)
    ).all()
    mapping: dict[str, int] = {}
    for row in rows:
        order = int(row.sort_order)
        if row.rarity_code:
            mapping[row.rarity_code.upper()] = order
        mapping[row.name.upper()] = order
    return mapping


def _bulk_rarity_sort_order(rarity_code: str, sort_map: dict[str, int]) -> int:
    normalized = normalize_rarity_code(rarity_code)
    bare = normalized.strip("()").upper()
    if bare in sort_map:
        return sort_map[bare]
    resolved = resolve_rarity(rarity_code)
    if resolved is not None:
        if resolved.code.upper() in sort_map:
            return sort_map[resolved.code.upper()]
        if resolved.name.upper() in sort_map:
            return sort_map[resolved.name.upper()]
    return 9999


def _bulk_item_matches_default_variant(item: CollectionItem) -> bool:
    condition = normalize_collection_condition(item.condition) or BULK_DEFAULT_CONDITION
    edition = normalize_collection_edition(item.edition)
    return condition == BULK_DEFAULT_CONDITION and edition == BULK_DEFAULT_EDITION


def _bulk_grid_baseline(
    *,
    quantity: int,
    trade_quantity: int,
    folder_name: str | None,
    collection_item_id: int | None,
) -> dict:
    return {
        "quantity": int(quantity),
        "trade_quantity": int(trade_quantity),
        "folder_name": folder_name,
        "collection_item_id": collection_item_id,
    }


def _bulk_build_row(
    *,
    row_id: str,
    printing: Printing,
    card: Card | None,
    rarity_sort: int,
    today: str,
    item: CollectionItem | None = None,
    allocation: CollectionItemFolder | None = None,
) -> dict:
    trade_q = int(item.trade_quantity) if item else 0
    if allocation is not None:
        folder_name = allocation.folder.name if allocation.folder else None
        folder_id = allocation.folder_id
        quantity = int(item.quantity) if item else int(allocation.quantity)
        allocation_id = allocation.id
        collection_item_id = item.id if item else None
    elif item is not None:
        folder_name = None
        folder_id = None
        quantity = int(item.quantity)
        allocation_id = None
        collection_item_id = item.id
    else:
        folder_name = None
        folder_id = None
        quantity = 0
        allocation_id = None
        collection_item_id = None

    condition = (
        normalize_collection_condition(item.condition) if item else BULK_DEFAULT_CONDITION
    ) or BULK_DEFAULT_CONDITION
    edition = (
        normalize_collection_edition(item.edition) if item else BULK_DEFAULT_EDITION
    )
    language = (item.language if item else None) or BULK_DEFAULT_LANGUAGE
    price_bought = item.price_bought if item else None
    date_bought = item.date_bought if item else today

    resolved = resolve_rarity(printing.set_rarity_code)
    rarity_name = (
        resolved.name if resolved is not None else printing.set_rarity
    )
    expansion = set_abbr_from_code(printing.set_code)
    total_q = quantity + trade_q
    baseline = _bulk_grid_baseline(
        quantity=quantity,
        trade_quantity=trade_q,
        folder_name=folder_name,
        collection_item_id=collection_item_id,
    )
    return {
        "row_id": row_id,
        "printing_id": printing.id,
        "collection_item_id": collection_item_id,
        "allocation_id": allocation_id,
        "folder_id": folder_id,
        "folder_name": folder_name,
        "quantity": quantity,
        "trade_quantity": trade_q,
        "total_quantity": total_q,
        "card_name": card.name if card else None,
        "expansion_code": expansion,
        "set_name": printing.set_name,
        "set_code": printing.set_code,
        "rarity_name": rarity_name,
        "rarity_code": printing.set_rarity_code,
        "rarity_sort_order": rarity_sort,
        "condition": condition,
        "edition": edition,
        "language": language,
        "price_bought": price_bought,
        "date_bought": date_bought,
        "owned": total_q > 0,
        "baseline": baseline,
    }


def _bulk_sort_rows(rows: list[dict], sort: list[dict] | None) -> list[dict]:
    if not sort:
        sort = [
            {"field": "set_code", "dir": "asc"},
            {"field": "rarity_sort_order", "dir": "asc"},
        ]

    def sort_key(row: dict):
        keys = []
        for spec in sort:
            field = spec.get("field", "set_code")
            direction = spec.get("dir", "asc")
            value = row.get(field)
            if value is None:
                value = ""
            if isinstance(value, str):
                value = value.lower()
            keys.append(value if direction == "asc" else _bulk_invert_sort_value(value))
        return tuple(keys)

    return sorted(rows, key=sort_key)


def _bulk_invert_sort_value(value):
    if isinstance(value, (int, float)):
        return -value
    if isinstance(value, str):
        return tuple(-ord(ch) for ch in value)
    return value


def list_bulk_collection_grid(
    session: Session,
    *,
    user_id: int,
    set_code: str,
    q: str | None = None,
    sort: list[dict] | None = None,
) -> tuple[list[dict], int, str]:
    raw = (set_code or "").strip()
    if not raw:
        raise ValueError("Set code is required")
    abbr = set_abbr_from_code(raw) or raw.upper()

    stmt = (
        select(Printing)
        .join(Card, Printing.card_id == Card.id)
        .where(Printing.set_code.ilike(f"{abbr}-%"))
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Card.name.ilike(like),
                Printing.set_code.ilike(like),
                Printing.set_name.ilike(like),
            )
        )

    printings = (
        session.execute(stmt.options(joinedload(Printing.card)).order_by(Printing.set_code))
        .unique()
        .scalars()
        .all()
    )

    rarity_sort_map = _bulk_rarity_sort_map(session)
    today = date.today().isoformat()

    items = (
        session.execute(
            select(CollectionItem)
            .options(
                joinedload(CollectionItem.folder_allocations).joinedload(
                    CollectionItemFolder.folder
                )
            )
            .where(
                CollectionItem.user_id == user_id,
                CollectionItem.set_code.ilike(f"{abbr}-%"),
            )
        )
        .unique()
        .scalars()
        .all()
    )

    items_by_printing: dict[tuple[str, str], list[CollectionItem]] = defaultdict(list)
    for item in items:
        key = (item.set_code, normalize_rarity_code(item.rarity_code))
        items_by_printing[key].append(item)

    rows: list[dict] = []
    for printing in printings:
        card = printing.card
        rarity_sort = _bulk_rarity_sort_order(printing.set_rarity_code, rarity_sort_map)
        key = (printing.set_code, normalize_rarity_code(printing.set_rarity_code))
        matched_items = items_by_printing.get(key, [])

        for item in matched_items:
            allocations = list(item.folder_allocations)
            if allocations:
                for allocation in allocations:
                    rows.append(
                        _bulk_build_row(
                            row_id=f"r-{item.id}-a{allocation.id}",
                            printing=printing,
                            card=card,
                            rarity_sort=rarity_sort,
                            today=today,
                            item=item,
                            allocation=allocation,
                        )
                    )
            else:
                rows.append(
                    _bulk_build_row(
                        row_id=f"r-{item.id}-a0",
                        printing=printing,
                        card=card,
                        rarity_sort=rarity_sort,
                        today=today,
                        item=item,
                    )
                )

        if not any(_bulk_item_matches_default_variant(item) for item in matched_items):
            rows.append(
                _bulk_build_row(
                    row_id=f"p-{printing.id}-default",
                    printing=printing,
                    card=card,
                    rarity_sort=rarity_sort,
                    today=today,
                )
            )

    rows = _bulk_sort_rows(rows, sort)
    return rows, len(rows), abbr


def bulk_collection_grid_meta(session: Session, *, user_id: int) -> dict:
    folders = list_collection_folders(session, user_id=user_id)
    return {
        "folders": folders,
        "conditions": list(COLLECTION_CONDITIONS),
        "editions": list(COLLECTION_EDITIONS),
        "languages": list(
            (
                "English",
                "French",
                "Italian",
                "German",
                "Spanish",
                "Portuguese",
            )
        ),
    }


def _bulk_change_eligible(change: dict) -> bool:
    qty = int(change.get("quantity") or 0)
    trade = int(change.get("trade_quantity") or 0)
    baseline = change.get("baseline") or {}
    base_qty = int(baseline.get("quantity") or 0)
    base_trade = int(baseline.get("trade_quantity") or 0)
    if qty > 0 or trade > 0:
        return True
    if base_qty > 0 or base_trade > 0:
        return True
    return False


def _bulk_folder_row_alloc_qty(row: dict) -> int:
    qty = int(row.get("quantity") or 0)
    if qty > 0:
        return qty
    return int(row.get("trade_quantity") or 0)


def _bulk_folder_rows(group_changes: list[dict], *, trade_q: int) -> list[dict]:
    keeper_rows = [row for row in group_changes if int(row.get("quantity") or 0) > 0]
    if keeper_rows:
        return keeper_rows
    if trade_q <= 0:
        return []
    return [row for row in group_changes if (row.get("folder_name") or "").strip()]


def save_bulk_collection_grid(
    session: Session,
    *,
    user_id: int,
    set_code: str,
    changes: list[dict],
    progress_callback=None,
) -> dict:
    raw = (set_code or "").strip()
    if not raw:
        raise ValueError("Set code is required")
    abbr = set_abbr_from_code(raw) or raw.upper()

    if len(changes) > BULK_GRID_MAX_CHANGES:
        raise ValueError(f"Too many changes (max {BULK_GRID_MAX_CHANGES})")

    eligible = [change for change in changes if _bulk_change_eligible(change)]
    if not eligible:
        return {
            "printings_updated": 0,
            "quantities_added": 0,
            "trade_quantities_added": 0,
            "items_created": 0,
            "items_updated": 0,
            "items_deleted": 0,
        }

    groups: dict[tuple[str, str, str, str | None], list[dict]] = defaultdict(list)
    for change in eligible:
        rarity_code = normalize_rarity_code(change["rarity_code"])
        key = collection_item_key(
            change["set_code"].strip(),
            rarity_code,
            edition=change.get("edition"),
            condition=change.get("condition"),
        )
        groups[key].append(change)

    printings_updated: set[tuple[str, str]] = set()
    quantities_added = 0
    trade_quantities_added = 0
    items_created = 0
    items_updated = 0
    items_deleted = 0

    total_groups = len(groups)
    progress_throttle = ProgressThrottle() if progress_callback else None

    for group_index, (key, group_changes) in enumerate(groups.items(), start=1):
        set_code_key, rarity_code, edition, condition = key
        trade_q = max(int(row.get("trade_quantity") or 0) for row in group_changes)
        folder_rows = _bulk_folder_rows(group_changes, trade_q=trade_q)
        total_qty = sum(int(row.get("quantity") or 0) for row in folder_rows)

        if total_qty > 0:
            for row in folder_rows:
                if not (row.get("folder_name") or "").strip():
                    raise ValueError(
                        f"Folder is required for {set_code_key} "
                        f"({rarity_display(rarity_code)})"
                    )
        elif trade_q > 0 and folder_rows:
            for row in folder_rows:
                if not (row.get("folder_name") or "").strip():
                    raise ValueError(
                        f"Folder is required for {set_code_key} "
                        f"({rarity_display(rarity_code)})"
                    )

        baseline_qty = max(int(row.get("baseline", {}).get("quantity") or 0) for row in group_changes)
        baseline_trade = max(
            int(row.get("baseline", {}).get("trade_quantity") or 0)
            for row in group_changes
        )

        existing = find_collection_item_by_identity(
            session,
            user_id=user_id,
            set_code=set_code_key,
            rarity_code=rarity_code,
            edition=edition,
            condition=condition,
        )

        if total_qty == 0 and trade_q == 0:
            if existing is not None:
                for row in group_changes:
                    item_id = row.get("collection_item_id")
                    if item_id is not None and item_id != existing.id:
                        raise ValueError("Collection item not found")
                session.delete(existing)
                items_deleted += 1
                printings_updated.add((set_code_key, rarity_code))
                quantities_added += max(0, -baseline_qty)
                trade_quantities_added += max(0, -baseline_trade)
            continue

        metadata = group_changes[0]
        for row in group_changes:
            item_id = row.get("collection_item_id")
            if item_id is not None:
                item = session.get(CollectionItem, item_id)
                if not item or item.user_id != user_id:
                    raise ValueError("Collection item not found")
                if existing is not None and item.id != existing.id:
                    raise ValueError("Collection item not found")

        printing = session.get(Printing, metadata["printing_id"])
        if printing is None:
            raise ValueError("Printing not found")
        if set_abbr_from_code(printing.set_code) != abbr:
            raise ValueError("Printing not found for set")

        folder_allocations: list[dict] = []
        merged_folders: dict[int | None, int] = {}
        for row in folder_rows:
            folder = get_or_create_folder(
                session, user_id, (row.get("folder_name") or "").strip()
            )
            folder_id = folder.id if folder else None
            merged_folders[folder_id] = merged_folders.get(folder_id, 0) + _bulk_folder_row_alloc_qty(
                row
            )
        for folder_id, qty in merged_folders.items():
            folder_allocations.append({"folder_id": folder_id, "quantity": qty})

        card_name = printing.card.name if printing.card else None

        if existing is None:
            item = CollectionItem(
                user_id=user_id,
                set_code=set_code_key,
                rarity_code=rarity_code,
                card_name=card_name,
                expansion_code=set_abbr_from_code(set_code_key),
                set_name=printing.set_name,
                quantity=total_qty,
                trade_quantity=trade_q,
                condition=condition,
                edition=edition,
                language=metadata.get("language") or BULK_DEFAULT_LANGUAGE,
                price_bought=metadata.get("price_bought"),
                date_bought=metadata.get("date_bought"),
                printing_id=printing.id,
            )
            session.add(item)
            session.flush()
            if folder_allocations:
                set_item_folder_allocations(
                    session,
                    user_id=user_id,
                    item=item,
                    allocations=folder_allocations,
                )
            else:
                item.folder_allocations.clear()
                session.flush()
            items_created += 1
            quantities_added += max(0, total_qty - baseline_qty)
            trade_quantities_added += max(0, trade_q - baseline_trade)
        else:
            old_qty = int(existing.quantity)
            old_trade = int(existing.trade_quantity)
            existing.quantity = total_qty
            existing.trade_quantity = trade_q
            existing.language = metadata.get("language") or existing.language
            if metadata.get("price_bought") is not None:
                existing.price_bought = metadata.get("price_bought")
            if metadata.get("date_bought"):
                existing.date_bought = metadata.get("date_bought")
            if not existing.printing_id:
                existing.printing_id = printing.id
            if card_name and not existing.card_name:
                existing.card_name = card_name
            if folder_allocations:
                set_item_folder_allocations(
                    session,
                    user_id=user_id,
                    item=existing,
                    allocations=folder_allocations,
                )
            else:
                existing.folder_allocations.clear()
                session.flush()
            items_updated += 1
            qty_delta = total_qty - old_qty
            trade_delta = trade_q - old_trade
            if qty_delta > 0:
                quantities_added += qty_delta
            if trade_delta > 0:
                trade_quantities_added += trade_delta

        printings_updated.add((set_code_key, rarity_code))

        if progress_callback and (
            progress_throttle is None
            or progress_throttle.should_emit(group_index)
            or group_index == total_groups
        ):
            progress_callback(
                {
                    "phase": "saving",
                    "current": group_index,
                    "total": total_groups,
                    "message": f"Saving {group_index} of {total_groups} printings…",
                }
            )

    session.commit()
    return {
        "printings_updated": len(printings_updated),
        "quantities_added": max(0, quantities_added),
        "trade_quantities_added": max(0, trade_quantities_added),
        "items_created": items_created,
        "items_updated": items_updated,
        "items_deleted": items_deleted,
    }
