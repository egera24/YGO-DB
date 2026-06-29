"""Price-ordered rarity assignment for Cardmarket catalog singles."""

from __future__ import annotations

from dataclasses import dataclass

from ygo_app.cardmarket.catalog.errors import AmbiguousPriceOrderError, PrintingCountMismatchError


@dataclass
class CmPricedProduct:
    id_product: int
    name: str
    id_expansion: int
    id_metacard: int
    trend: float | None
    avg: float | None
    low: float | None


@dataclass
class YugipediaPrintingRef:
    set_code: str
    rarity_code: str
    set_rarity: str | None
    card_name: str
    card_id: int
    rarity_sort_order: int


def _price_sort_key(product: CmPricedProduct) -> tuple:
    trend = product.trend if product.trend is not None else float("inf")
    avg = product.avg if product.avg is not None else float("inf")
    return (trend, avg)


def _check_ambiguous_ties(products: list[CmPricedProduct]) -> None:
    for i in range(len(products) - 1):
        left = products[i]
        right = products[i + 1]
        if _price_sort_key(left) == _price_sort_key(right):
            raise AmbiguousPriceOrderError(
                f"Tied Cardmarket prices for products {left.id_product} and {right.id_product}",
                set_code=None,
                card_name=left.name,
            )


def assign_rarities_by_price(
    *,
    set_code: str,
    card_name: str,
    cm_products: list[CmPricedProduct],
    yugipedia_printings: list[YugipediaPrintingRef],
) -> list[tuple[YugipediaPrintingRef, CmPricedProduct]]:
    if len(cm_products) != len(yugipedia_printings):
        raise PrintingCountMismatchError(
            f"Count mismatch for {set_code} / {card_name}: "
            f"yugipedia={len(yugipedia_printings)} cardmarket={len(cm_products)}",
            set_code=set_code,
            card_name=card_name,
            yugipedia_count=len(yugipedia_printings),
            cardmarket_count=len(cm_products),
        )

    sorted_cm = sorted(
        cm_products,
        key=lambda p: (_price_sort_key(p), p.id_product),
    )
    sorted_yg = sorted(yugipedia_printings, key=lambda p: (p.rarity_sort_order, p.rarity_code))

    if len(sorted_cm) > 1:
        _check_ambiguous_ties(sorted_cm)

    return list(zip(sorted_yg, sorted_cm, strict=True))
