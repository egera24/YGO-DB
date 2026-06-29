"""Map Yugipedia TCG sets to Cardmarket idExpansion via nonsingles name containment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ygo_app.cardmarket.catalog.errors import ExpansionMappingError
from ygo_app.cardmarket.catalog.expansion_conflict import resolve_conflicting_expansion_ids
from ygo_app.cardmarket.catalog.expansion_aliases import (
    expansion_aliases_for_abbr,
    nonsingle_matches_alias,
)
from ygo_app.cardmarket.catalog.normalize import (
    excluded_nonsingle_expansion_ids,
    expansion_name_contains,
    is_championship_prize_set,
    is_collectible_tin_set,
    is_non_tcg_nonsingle_product,
    product_line_matches_yugipedia_set,
    structure_deck_cardmarket_name,
)
from ygo_app.models import CardmarketExpansion, Printing, TcgSet


@dataclass
class ExpansionMapping:
    abbr: str
    set_name: str
    expansion_id: int
    matched_product_names: list[str]


def _is_eligible_nonsingle(row: dict, excluded_exp_ids: set[int]) -> bool:
    if is_non_tcg_nonsingle_product(str(row.get("name") or "")):
        return False
    exp_id = row.get("idExpansion")
    if exp_id is not None and int(exp_id) in excluded_exp_ids:
        return False
    return True


def _nonsingle_hits(
    tcg_nonsingles: list[dict],
    tcg_set: TcgSet,
    *,
    matching_name: str | None = None,
) -> list[dict]:
    hits: list[dict] = []
    for row in tcg_nonsingles:
        product_name = str(row.get("name") or "")
        if not expansion_name_contains(
            product_name, tcg_set.name, matching_name=matching_name
        ):
            continue
        if not product_line_matches_yugipedia_set(product_name, tcg_set.name):
            continue
        hits.append(row)
    return hits


def _nonsingle_hits_by_aliases(
    tcg_nonsingles: list[dict],
    tcg_set: TcgSet,
    aliases: tuple[str, ...],
) -> list[dict]:
    hits: list[dict] = []
    for row in tcg_nonsingles:
        product_name = str(row.get("name") or "")
        if not any(nonsingle_matches_alias(product_name, alias) for alias in aliases):
            continue
        if not product_line_matches_yugipedia_set(product_name, tcg_set.name):
            continue
        hits.append(row)
    return hits


def map_expansions_from_nonsingles(
    session: Session,
    nonsingles: list[dict],
    *,
    singles: list[dict] | None = None,
    price_rows: list[dict] | None = None,
    upsert: bool = True,
) -> tuple[dict[str, ExpansionMapping], list[dict]]:
    tcg_sets = session.scalars(
        select(TcgSet).where(TcgSet.region == "TCG").order_by(TcgSet.abbr)
    ).all()

    excluded_exp_ids = excluded_nonsingle_expansion_ids(nonsingles)
    tcg_nonsingles = [row for row in nonsingles if _is_eligible_nonsingle(row, excluded_exp_ids)]

    mappings: dict[str, ExpansionMapping] = {}
    errors: list[dict] = []
    skipped: list[dict] = []

    for tcg_set in tcg_sets:
        if is_championship_prize_set(tcg_set.name):
            skipped.append(
                {
                    "abbr": tcg_set.abbr,
                    "set_name": tcg_set.name,
                    "reason": "championship_prize_cards",
                }
            )
            continue

        if is_collectible_tin_set(tcg_set.name):
            skipped.append(
                {
                    "abbr": tcg_set.abbr,
                    "set_name": tcg_set.name,
                    "reason": "collectible_tins",
                }
            )
            continue

        card_count = session.scalar(
            select(func.count(func.distinct(Printing.card_id))).where(
                Printing.set_code.like(f"{tcg_set.abbr}-%")
            )
        )
        if (card_count or 0) < 2:
            skipped.append(
                {
                    "abbr": tcg_set.abbr,
                    "set_name": tcg_set.name,
                    "reason": "insufficient_yugipedia_cards",
                }
            )
            continue

        aliases = expansion_aliases_for_abbr(tcg_set.abbr)
        if aliases:
            hits = _nonsingle_hits_by_aliases(tcg_nonsingles, tcg_set, aliases)
        else:
            hits = _nonsingle_hits(tcg_nonsingles, tcg_set)
            if not hits:
                alternate = structure_deck_cardmarket_name(tcg_set.name)
                if alternate:
                    hits = _nonsingle_hits(
                        tcg_nonsingles, tcg_set, matching_name=alternate
                    )
        expansion_ids = sorted({int(row["idExpansion"]) for row in hits if row.get("idExpansion") is not None})

        if len(expansion_ids) == 0:
            errors.append(
                {
                    "abbr": tcg_set.abbr,
                    "set_name": tcg_set.name,
                    "reason": "no_nonsingle_match",
                    "expansion_ids": [],
                }
            )
            continue

        if len(expansion_ids) > 1:
            matched_names = [str(row.get("name") or "") for row in hits]
            if singles is not None and price_rows is not None:
                try:
                    resolved_id = resolve_conflicting_expansion_ids(
                        session,
                        abbr=tcg_set.abbr,
                        set_name=tcg_set.name,
                        candidate_ids=expansion_ids,
                        singles=singles,
                        price_rows=price_rows,
                        matched_names=matched_names,
                    )
                except ExpansionMappingError as exc:
                    if exc.details:
                        errors.extend(exc.details)
                    else:
                        errors.append(
                            {
                                "abbr": tcg_set.abbr,
                                "set_name": tcg_set.name,
                                "reason": "conflicting_idExpansion",
                                "expansion_ids": expansion_ids,
                                "matched_names": matched_names[:10],
                            }
                        )
                    continue
                expansion_ids = [resolved_id]
            else:
                errors.append(
                    {
                        "abbr": tcg_set.abbr,
                        "set_name": tcg_set.name,
                        "reason": "conflicting_idExpansion",
                        "expansion_ids": expansion_ids,
                        "matched_names": matched_names[:10],
                    }
                )
                continue

        mapping = ExpansionMapping(
            abbr=tcg_set.abbr,
            set_name=tcg_set.name,
            expansion_id=expansion_ids[0],
            matched_product_names=[str(row.get("name") or "") for row in hits],
        )
        mappings[tcg_set.abbr] = mapping

        if upsert:
            row = session.get(CardmarketExpansion, mapping.expansion_id)
            if row is None:
                row = CardmarketExpansion(
                    expansion_id=mapping.expansion_id,
                    expansion_code=tcg_set.abbr,
                    expansion_name=tcg_set.name,
                    fetched_at=datetime.utcnow(),
                )
                session.add(row)
            else:
                row.expansion_code = tcg_set.abbr
                row.expansion_name = tcg_set.name
                row.fetched_at = datetime.utcnow()

    if errors:
        raise ExpansionMappingError(
            f"Failed to map {len(errors)} TCG set(s) to Cardmarket expansions",
            details=errors,
        )

    return mappings, skipped
