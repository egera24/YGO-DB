"""Match Yugipedia printings to Cardmarket catalog singles + prices."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ygo_app.cardmarket.catalog.errors import AmbiguousPriceOrderError, PrintingCountMismatchError
from ygo_app.cardmarket.catalog.expansion_map import ExpansionMapping
from ygo_app.cardmarket.catalog.normalize import normalize_card_name
from ygo_app.cardmarket.catalog.rarity_guess import (
    CmPricedProduct,
    YugipediaPrintingRef,
    assign_rarities_by_price,
)
from ygo_app.cardmarket.export_schema import row_from_db
from ygo_app.models import Card, Printing, RarityPriceRank


YGO_SINGLE_CATEGORY = 5


def _build_price_index(price_rows: list[dict]) -> dict[int, dict]:
    return {int(row["idProduct"]): row for row in price_rows if row.get("idProduct") is not None}


def _build_rarity_rank_index(session: Session) -> dict[str, int]:
    rows = session.scalars(select(RarityPriceRank).order_by(RarityPriceRank.sort_order)).all()
    by_name = {row.name: row.sort_order for row in rows}
    by_code = {
        (row.rarity_code or "").upper(): row.sort_order
        for row in rows
        if row.rarity_code
    }
    return {"by_name": by_name, "by_code": by_code}


def _rarity_sort_order(
    *,
    set_rarity: str | None,
    rarity_code: str | None,
    rank_index: dict,
) -> int:
    by_name: dict[str, int] = rank_index["by_name"]
    by_code: dict[str, int] = rank_index["by_code"]
    if set_rarity and set_rarity in by_name:
        return by_name[set_rarity]
    if rarity_code and rarity_code.upper() in by_code:
        return by_code[rarity_code.upper()]
    return 9999


def _cm_product_url(id_product: int, name: str) -> str:
    slug = name.replace(" ", "-")
    return f"https://www.cardmarket.com/en/YuGiOh/Products/Singles/{slug}/{id_product}"


def _dedupe_cm_matches_by_expansion_preference(
    cm_matches: list[dict],
    *,
    expansion_match_counts: dict[int, int] | None,
) -> list[dict]:
    if not expansion_match_counts or len(cm_matches) <= 1:
        return cm_matches

    by_expansion: dict[int, list[dict]] = defaultdict(list)
    for row in cm_matches:
        exp_id = row.get("idExpansion")
        if exp_id is None:
            continue
        by_expansion[int(exp_id)].append(row)

    if len(by_expansion) <= 1:
        return cm_matches

    best = max(expansion_match_counts.get(exp_id, 0) for exp_id in by_expansion)
    preferred = [
        exp_id for exp_id in by_expansion if expansion_match_counts.get(exp_id, 0) == best
    ]
    if len(preferred) == 1:
        return by_expansion[preferred[0]]
    return cm_matches


def match_printings_to_catalog(
    session: Session,
    *,
    singles: list[dict],
    price_rows: list[dict],
    expansion_mappings: dict[str, ExpansionMapping],
) -> tuple[list[dict], dict[str, int], list[dict]]:
    price_index = _build_price_index(price_rows)
    rank_index = _build_rarity_rank_index(session)

    singles_by_expansion: dict[int, list[dict]] = defaultdict(list)
    for row in singles:
        if int(row.get("idCategory") or 0) != YGO_SINGLE_CATEGORY:
            continue
        exp_id = row.get("idExpansion")
        if exp_id is None:
            continue
        singles_by_expansion[int(exp_id)].append(row)

    export_rows: list[dict] = []
    rejections: list[dict] = []
    stats = {
        "matched": 0,
        "cards_processed": 0,
        "rejected_cards": 0,
        "expansions": len(expansion_mappings),
    }

    for abbr, mapping in expansion_mappings.items():
        cm_rows: list[dict] = []
        for exp_id in mapping.expansion_ids:
            cm_rows.extend(singles_by_expansion.get(exp_id, []))
        cm_by_card_name: dict[str, list[dict]] = defaultdict(list)
        for row in cm_rows:
            cm_by_card_name[normalize_card_name(str(row.get("name") or ""))].append(row)

        printings = session.scalars(
            select(Printing)
            .options(joinedload(Printing.card))
            .where(Printing.set_code.like(f"{abbr}-%"))
        ).all()

        by_card_id: dict[int, list[Printing]] = defaultdict(list)
        for printing in printings:
            if printing.card is None:
                continue
            by_card_id[printing.card_id].append(printing)

        for card_id, card_printings in by_card_id.items():
            stats["cards_processed"] += 1
            card: Card = card_printings[0].card
            cm_matches = cm_by_card_name.get(normalize_card_name(card.name), [])
            cm_matches = _dedupe_cm_matches_by_expansion_preference(
                cm_matches,
                expansion_match_counts=mapping.expansion_match_counts,
            )

            yg_refs = [
                YugipediaPrintingRef(
                    set_code=printing.set_code,
                    rarity_code=printing.set_rarity_code,
                    set_rarity=printing.set_rarity,
                    card_name=card.name,
                    card_id=card_id,
                    rarity_sort_order=_rarity_sort_order(
                        set_rarity=printing.set_rarity,
                        rarity_code=printing.set_rarity_code,
                        rank_index=rank_index,
                    ),
                )
                for printing in card_printings
            ]

            cm_priced = []
            for row in cm_matches:
                pid = int(row["idProduct"])
                price = price_index.get(pid, {})
                cm_priced.append(
                    CmPricedProduct(
                        id_product=pid,
                        name=str(row.get("name") or card.name),
                        id_expansion=int(row["idExpansion"]),
                        id_metacard=int(row.get("idMetacard") or 0),
                        trend=price.get("trend"),
                        avg=price.get("avg"),
                        low=price.get("low"),
                    )
                )

            try:
                pairs = assign_rarities_by_price(
                    set_code=abbr,
                    card_name=card.name,
                    cm_products=cm_priced,
                    yugipedia_printings=yg_refs,
                )
            except PrintingCountMismatchError as exc:
                stats["rejected_cards"] += 1
                rejections.append(
                    {
                        "reason": "count_mismatch",
                        "abbr": abbr,
                        "set_code": exc.set_code or abbr,
                        "card_name": exc.card_name or card.name,
                        "yugipedia_count": exc.yugipedia_count,
                        "cardmarket_count": exc.cardmarket_count,
                    }
                )
                continue
            except AmbiguousPriceOrderError as exc:
                stats["rejected_cards"] += 1
                rejections.append(
                    {
                        "reason": "ambiguous_price_order",
                        "abbr": abbr,
                        "set_code": exc.set_code or abbr,
                        "card_name": exc.card_name or card.name,
                    }
                )
                continue

            for yg_ref, cm_product in pairs:
                export_rows.append(
                    row_from_db(
                        set_code=yg_ref.set_code,
                        rarity_code=yg_ref.rarity_code,
                        cardmarket_product_id=cm_product.id_product,
                        cardmarket_url=_cm_product_url(cm_product.id_product, cm_product.name),
                        low_price=cm_product.low,
                        avg_price=cm_product.avg,
                        trend_price=cm_product.trend,
                        discovery_status="matched",
                    )
                )
                stats["matched"] += 1

    return export_rows, stats, rejections
