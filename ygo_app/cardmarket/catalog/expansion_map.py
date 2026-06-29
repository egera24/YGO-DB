"""Map Yugipedia TCG sets to Cardmarket idExpansion via nonsingles name containment."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ygo_app.cardmarket.catalog.errors import ExpansionMappingError
from ygo_app.cardmarket.catalog.expansion_conflict import resolve_or_merge_expansion_ids
from ygo_app.cardmarket.catalog.expansion_aliases import (
    expansion_aliases_for_abbr,
    nonsingle_matches_alias,
)
from ygo_app.cardmarket.catalog.normalize import (
    alternate_matching_names,
    excluded_nonsingle_expansion_ids,
    expansion_name_contains,
    is_championship_prize_set,
    is_collectible_tin_set,
    is_non_tcg_nonsingle_product,
    is_promotional_or_participation_set,
    product_line_matches_yugipedia_set,
)
from ygo_app.models import CardmarketExpansion, Printing, TcgSet


@dataclass
class ExpansionMapping:
    abbr: str
    set_name: str
    expansion_ids: tuple[int, ...]
    matched_product_names: list[str]
    expansion_match_counts: dict[int, int] | None = None

    @property
    def expansion_id(self) -> int:
        return self.expansion_ids[0]


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
) -> tuple[dict[str, ExpansionMapping], list[dict], list[dict]]:
    tcg_sets = session.scalars(
        select(TcgSet).where(TcgSet.region == "TCG").order_by(TcgSet.abbr)
    ).all()

    excluded_exp_ids = excluded_nonsingle_expansion_ids(nonsingles)
    tcg_nonsingles = [row for row in nonsingles if _is_eligible_nonsingle(row, excluded_exp_ids)]

    mappings: dict[str, ExpansionMapping] = {}
    errors: list[dict] = []
    skipped: list[dict] = []
    # session.get() does not see unflushed inserts when autoflush=False (SessionLocal default).
    pending_expansions: dict[int, CardmarketExpansion] = {}

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

        if is_promotional_or_participation_set(tcg_set.name):
            skipped.append(
                {
                    "abbr": tcg_set.abbr,
                    "set_name": tcg_set.name,
                    "reason": "promotional_or_participation_cards",
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
                for alternate in alternate_matching_names(tcg_set.name):
                    hits = _nonsingle_hits(
                        tcg_nonsingles, tcg_set, matching_name=alternate
                    )
                    if hits:
                        break
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

        expansion_match_counts: dict[int, int] | None = None

        if len(expansion_ids) > 1:
            matched_names = [str(row.get("name") or "") for row in hits]
            if singles is not None and price_rows is not None:
                try:
                    expansion_ids, expansion_match_counts = resolve_or_merge_expansion_ids(
                        session,
                        abbr=tcg_set.abbr,
                        set_name=tcg_set.name,
                        candidate_ids=expansion_ids,
                        singles=singles,
                        price_rows=price_rows,
                        matched_names=matched_names,
                    )
                    expansion_ids = list(expansion_ids)
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
            expansion_ids=tuple(expansion_ids),
            matched_product_names=[str(row.get("name") or "") for row in hits],
            expansion_match_counts=expansion_match_counts,
        )
        mappings[tcg_set.abbr] = mapping

        if upsert:
            for exp_id in mapping.expansion_ids:
                row = session.get(CardmarketExpansion, exp_id)
                if row is None:
                    pending_row = pending_expansions.get(exp_id)
                    if pending_row is not None:
                        # #region agent log
                        with open("debug-a7888b.log", "a", encoding="utf-8") as _dbg_f:
                            _dbg_f.write(
                                json.dumps(
                                    {
                                        "sessionId": "a7888b",
                                        "hypothesisId": "H1",
                                        "location": "expansion_map.py:upsert",
                                        "message": "session.get missed pending expansion",
                                        "data": {"exp_id": exp_id, "abbr": tcg_set.abbr},
                                        "timestamp": int(time.time() * 1000),
                                    }
                                )
                                + "\n"
                            )
                        # #endregion
                        row = pending_row
                if row is None:
                    row = CardmarketExpansion(
                        expansion_id=exp_id,
                        expansion_code=tcg_set.abbr,
                        expansion_name=tcg_set.name,
                        fetched_at=datetime.utcnow(),
                    )
                    session.add(row)
                    pending_expansions[exp_id] = row
                else:
                    row.expansion_code = tcg_set.abbr
                    row.expansion_name = tcg_set.name
                    row.fetched_at = datetime.utcnow()

    return mappings, skipped, errors
