"""Resolve conflicting Cardmarket idExpansion candidates using singles + prices."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ygo_app.cardmarket.catalog.errors import ExpansionMappingError
from ygo_app.cardmarket.catalog.normalize import normalize_card_name
from ygo_app.models import Printing

YGO_SINGLE_CATEGORY = 5
PRICE_FIELDS = ("trend", "avg", "low")


def _build_price_index(price_rows: list[dict]) -> dict[int, dict]:
    return {int(row["idProduct"]): row for row in price_rows if row.get("idProduct") is not None}


def _singles_by_expansion(singles: list[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = defaultdict(list)
    for row in singles:
        if int(row.get("idCategory") or 0) != YGO_SINGLE_CATEGORY:
            continue
        exp_id = row.get("idExpansion")
        if exp_id is None:
            continue
        grouped[int(exp_id)].append(row)
    return grouped


def _yugipedia_card_names(session: Session, abbr: str) -> list[str]:
    printings = session.scalars(
        select(Printing)
        .options(joinedload(Printing.card))
        .where(Printing.set_code.like(f"{abbr}-%"))
    ).all()
    names: list[str] = []
    seen: set[str] = set()
    for printing in printings:
        if printing.card is None:
            continue
        norm = normalize_card_name(printing.card.name)
        if norm and norm not in seen:
            seen.add(norm)
            names.append(printing.card.name)
    return names


def _price_fields_compatible(a: dict, b: dict) -> bool:
    for key in PRICE_FIELDS:
        va, vb = a.get(key), b.get(key)
        if va is not None and vb is not None and va != vb:
            return False
    return True


def _expansion_card_price_map(
    exp_id: int,
    singles_by_exp: dict[int, list[dict]],
    price_index: dict[int, dict],
) -> dict[str, dict]:
    card_prices: dict[str, dict] = {}
    for row in singles_by_exp.get(exp_id, []):
        norm = normalize_card_name(str(row.get("name") or ""))
        if not norm or norm in card_prices:
            continue
        price = price_index.get(int(row["idProduct"]))
        if price is not None:
            card_prices[norm] = price
    return card_prices


def _count_priced_yugipedia_matches(
    exp_id: int,
    yugipedia_card_names: list[str],
    singles_by_exp: dict[int, list[dict]],
    price_index: dict[int, dict],
) -> int:
    cm_by_name: dict[str, list[dict]] = defaultdict(list)
    for row in singles_by_exp.get(exp_id, []):
        cm_by_name[normalize_card_name(str(row.get("name") or ""))].append(row)

    matched = 0
    for card_name in yugipedia_card_names:
        norm = normalize_card_name(card_name)
        for row in cm_by_name.get(norm, []):
            if price_index.get(int(row["idProduct"])) is not None:
                matched += 1
                break
    return matched


def _pick_best_expansion(candidates: list[int], match_counts: dict[int, int]) -> int:
    best_count = max(match_counts[c] for c in candidates)
    tied = [c for c in candidates if match_counts[c] == best_count]
    return min(tied)


def _shared_card_names(card_maps: dict[int, dict[str, dict]]) -> set[str]:
    exp_ids = list(card_maps)
    shared: set[str] = set()
    for i, exp_a in enumerate(exp_ids):
        names_a = set(card_maps[exp_a])
        for exp_b in exp_ids[i + 1 :]:
            shared |= names_a & set(card_maps[exp_b])
    return shared


def resolve_conflicting_expansion_ids(
    session: Session,
    *,
    abbr: str,
    set_name: str,
    candidate_ids: list[int],
    singles: list[dict],
    price_rows: list[dict],
    matched_names: list[str],
) -> int:
    price_index = _build_price_index(price_rows)
    singles_by_exp = _singles_by_expansion(singles)
    yugipedia_names = _yugipedia_card_names(session, abbr)

    match_counts = {
        exp_id: _count_priced_yugipedia_matches(
            exp_id, yugipedia_names, singles_by_exp, price_index
        )
        for exp_id in candidate_ids
    }
    candidates = [exp_id for exp_id in candidate_ids if match_counts[exp_id] > 0]
    if not candidates:
        raise ExpansionMappingError(
            f"Failed to map TCG set {abbr} to Cardmarket expansions",
            details=[
                {
                    "abbr": abbr,
                    "set_name": set_name,
                    "reason": "conflicting_idExpansion",
                    "expansion_ids": candidate_ids,
                    "matched_names": matched_names[:10],
                }
            ],
        )

    if len(candidates) == 1:
        return candidates[0]

    card_maps = {
        exp_id: _expansion_card_price_map(exp_id, singles_by_exp, price_index)
        for exp_id in candidates
    }
    shared = _shared_card_names(card_maps)
    if shared:
        for card_norm in shared:
            priced = [card_maps[exp_id][card_norm] for exp_id in candidates if card_norm in card_maps[exp_id]]
            for i, price_a in enumerate(priced):
                for price_b in priced[i + 1 :]:
                    if not _price_fields_compatible(price_a, price_b):
                        raise ExpansionMappingError(
                            f"Failed to map TCG set {abbr} to Cardmarket expansions",
                            details=[
                                {
                                    "abbr": abbr,
                                    "set_name": set_name,
                                    "reason": "conflicting_idExpansion",
                                    "expansion_ids": candidate_ids,
                                    "matched_names": matched_names[:10],
                                    "card_name": card_norm,
                                }
                            ],
                        )

    return _pick_best_expansion(candidates, match_counts)
