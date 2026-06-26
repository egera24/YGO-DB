"""Job 4: join Cardmarket details JSON with Yugipedia catalog → export schema."""

from __future__ import annotations

from pathlib import Path

from ygo_app.cardmarket.artifact_io import load_json_list
from ygo_app.cardmarket.catalog_source import load_catalog_printings
from ygo_app.cardmarket.constants import DISCOVERY_MATCHED, DISCOVERY_UNMATCHED
from ygo_app.cardmarket.containment_matching import match_printings_to_cardmarket
from ygo_app.cardmarket.export_schema import build_export_payload, row_from_db, save_export
from ygo_app.cardmarket.incremental import find_duplicate_match_keys, raise_on_conflicts
from ygo_app.cardmarket.paths import (
    CARDMARKET_CARD_DETAILS_PATH,
    CARDMARKET_PRICES_PATH,
    DEFAULT_CATALOG_PATH,
)
from ygo_app.yugipedia.scrape_progress import log_line


def _detail_to_product(detail: dict) -> dict:
    card = detail.get("card_data") or {}
    price = detail.get("price_data") or {}
    return {
        "cardmarket_product_id": card.get("card_id"),
        "cardmarket_url": price.get("url"),
        "low_price": price.get("low_price"),
        "avg_price": price.get("avg_30_price"),
        "trend_price": price.get("trend_price"),
    }


def validate_export_match_keys(
    catalog: list[tuple[str, str, str | None]],
    details: list[dict],
) -> None:
    """Fail if any Yugipedia printing matches more than one Cardmarket product."""
    _matches, conflicts = match_printings_to_cardmarket(catalog, details)
    raise_on_conflicts(conflicts)


def validate_detail_duplicate_keys(details: list[dict]) -> None:
    """Fail if multiple Cardmarket products map to the same strict printing key."""
    conflicts = find_duplicate_match_keys(details)
    raise_on_conflicts(conflicts)


def export_prices_from_details(
    *,
    details_path: Path = CARDMARKET_CARD_DETAILS_PATH,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    output_path: Path = CARDMARKET_PRICES_PATH,
    limit: int | None = None,
    validate: bool = False,
) -> dict[str, int]:
    if not catalog_path.is_file():
        raise FileNotFoundError(
            f"Catalog JSON not found: {catalog_path}. "
            "Run Yugipedia scrape/import first or pass --catalog."
        )
    if not details_path.is_file():
        raise FileNotFoundError(
            f"Card details JSON not found: {details_path}. "
            "Run scrape_cardmarket_card_details first."
        )

    catalog = load_catalog_printings(None, catalog_path=catalog_path)
    if limit is not None:
        catalog = catalog[:limit]

    details = load_json_list(details_path)
    matches, conflicts = match_printings_to_cardmarket(catalog, details)
    if validate:
        raise_on_conflicts(conflicts)

    rows: list[dict] = []
    matched = 0
    unmatched = 0

    for set_code, rarity_code, rarity_name in catalog:
        key = (set_code, rarity_code)
        product_detail = matches.get(key)
        if product_detail:
            product = _detail_to_product(product_detail)
            rows.append(
                row_from_db(
                    set_code=set_code,
                    rarity_code=rarity_code,
                    cardmarket_product_id=product.get("cardmarket_product_id"),
                    cardmarket_url=product.get("cardmarket_url"),
                    low_price=product.get("low_price"),
                    avg_price=product.get("avg_price"),
                    trend_price=product.get("trend_price"),
                    discovery_status=DISCOVERY_MATCHED,
                )
            )
            matched += 1
        else:
            rows.append(
                row_from_db(
                    set_code=set_code,
                    rarity_code=rarity_code,
                    discovery_status=DISCOVERY_UNMATCHED,
                )
            )
            unmatched += 1

    payload = build_export_payload(rows)
    if conflicts:
        payload.setdefault("stats", {})["ambiguous_matches"] = len(conflicts)
    save_export(output_path, payload)
    log_line(
        f"[EXPORT] wrote {output_path} total={len(rows)} matched={matched} "
        f"unmatched={unmatched} ambiguous={len(conflicts)} "
        f"with_prices={payload['stats']['with_prices']}"
    )
    return {
        "total": len(rows),
        "matched": matched,
        "unmatched": unmatched,
        "ambiguous": len(conflicts),
    }
