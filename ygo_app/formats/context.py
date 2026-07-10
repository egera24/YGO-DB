"""Format context resolution for API and search."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ygo_app.formats.banlist import load_banlist_map, resolve_banlist_revision
from ygo_app.formats.genesys import load_genesys_points_map, resolve_genesys_point_list
from ygo_app.formats.registry import get_format_rules
from ygo_app.models import BanlistRevision, GenesysPointList


@dataclass
class FormatSearchContext:
    format_code: str
    rules: object
    point_list: GenesysPointList | None = None


@dataclass
class FormatContext:
    format_code: str
    rules: object
    banlist_revision: BanlistRevision | None = None
    banlist_map: dict[int, str] | None = None
    point_list: GenesysPointList | None = None
    points_map: dict[int, int] | None = None


def resolve_format_search_context(
    session: Session,
    format_code: str | None,
    *,
    genesys_point_list_id: int | None = None,
) -> FormatSearchContext | None:
    if not format_code:
        return None
    rules = get_format_rules(format_code)
    if not rules:
        return None

    point_list = None
    if rules.uses_point_list:
        point_list = resolve_genesys_point_list(session, genesys_point_list_id)

    return FormatSearchContext(
        format_code=format_code,
        rules=rules,
        point_list=point_list,
    )


def resolve_format_enrich_context(
    session: Session,
    format_code: str | None,
    *,
    banlist_revision_id: int | None = None,
    genesys_point_list_id: int | None = None,
) -> FormatContext | None:
    if not format_code:
        return None
    rules = get_format_rules(format_code)
    if not rules:
        return None

    banlist_revision = resolve_banlist_revision(session, rules, banlist_revision_id)
    banlist_map = load_banlist_map(session, banlist_revision) if banlist_revision else {}

    point_list = None
    points_map: dict[int, int] = {}
    if rules.uses_point_list:
        point_list = resolve_genesys_point_list(session, genesys_point_list_id)
        points_map = load_genesys_points_map(session, point_list)

    return FormatContext(
        format_code=format_code,
        rules=rules,
        banlist_revision=banlist_revision,
        banlist_map=banlist_map,
        point_list=point_list,
        points_map=points_map,
    )


def resolve_format_context(
    session: Session,
    format_code: str | None,
    *,
    banlist_revision_id: int | None = None,
    genesys_point_list_id: int | None = None,
) -> FormatContext | None:
    return resolve_format_enrich_context(
        session,
        format_code,
        banlist_revision_id=banlist_revision_id,
        genesys_point_list_id=genesys_point_list_id,
    )
