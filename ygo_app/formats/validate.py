"""Deck validation against format rules."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ygo_app.formats.banlist import (
    effective_max_copies,
    load_banlist_map,
    resolve_banlist_revision,
)
from ygo_app.formats.base import DeckValidation, FormatRules, ValidationIssue
from ygo_app.formats.genesys import (
    card_point_value,
    load_genesys_points_map,
    resolve_genesys_point_list,
)
from ygo_app.formats.pool import card_legal_in_format
from ygo_app.formats.registry import get_format_rules
from ygo_app.models import Card, Deck, DeckCard

EXTRA_DECK_MECHANICS = frozenset({"fusion", "synchro", "xyz", "link", "pendulum"})


def _card_mechanic(card: Card) -> str | None:
    if card.mechanic:
        return card.mechanic.lower()
    if card.frame_type:
        ft = card.frame_type.lower()
        if ft in EXTRA_DECK_MECHANICS:
            return ft
    return None


def _is_extra_deck_monster(card: Card) -> bool:
    mechanic = _card_mechanic(card)
    if mechanic in {"fusion", "synchro", "xyz", "link"}:
        return True
    if mechanic == "pendulum" and card.category and card.category.lower() == "monster":
        return False
    return False


def _validate_deck_sizes(
    rules: FormatRules,
    counts: dict[str, int],
    result: DeckValidation,
) -> None:
    main = counts.get("main", 0)
    extra = counts.get("extra", 0)
    side = counts.get("side", 0)

    if rules.main_min is not None and main < rules.main_min:
        result.errors.append(
            ValidationIssue(
                severity="error",
                code="main_too_small",
                message=f"Main Deck must contain at least {rules.main_min} cards (currently {main}).",
                zone="main",
            )
        )
    if rules.main_max is not None and main > rules.main_max:
        result.errors.append(
            ValidationIssue(
                severity="error",
                code="main_too_large",
                message=f"Main Deck can contain at most {rules.main_max} cards (currently {main}).",
                zone="main",
            )
        )
    if rules.extra_max is not None and extra > rules.extra_max:
        result.errors.append(
            ValidationIssue(
                severity="error",
                code="extra_too_large",
                message=f"Extra Deck can contain at most {rules.extra_max} cards (currently {extra}).",
                zone="extra",
            )
        )
    if rules.side_max is not None and side > rules.side_max:
        result.errors.append(
            ValidationIssue(
                severity="error",
                code="side_too_large",
                message=f"Side Deck can contain at most {rules.side_max} cards (currently {side}).",
                zone="side",
            )
        )

    if (
        rules.recommend_main_exact is not None
        and main >= (rules.main_min or 0)
        and main > rules.recommend_main_exact
    ):
        result.info.append(
            ValidationIssue(
                severity="info",
                code="main_consistency",
                message=(
                    f"It is highly recommended to stick to {rules.recommend_main_exact} cards "
                    f"in the Main Deck to increase consistency (currently {main})."
                ),
                zone="main",
            )
        )


def _validate_zone_placement(
    rules: FormatRules,
    deck_cards: list[tuple[DeckCard, Card]],
    result: DeckValidation,
) -> None:
    for dc, card in deck_cards:
        mechanic = _card_mechanic(card)
        is_extra_monster = _is_extra_deck_monster(card)

        if dc.zone == "main" and is_extra_monster:
            if mechanic and mechanic in rules.forbidden_main_mechanics:
                result.errors.append(
                    ValidationIssue(
                        severity="error",
                        code="wrong_zone_main",
                        message=f"{card.name} cannot be in the Main Deck.",
                        card_id=card.id,
                        zone="main",
                    )
                )

        if dc.zone == "extra":
            if not is_extra_monster and mechanic not in rules.allowed_extra_mechanics:
                if card.category and card.category.lower() != "monster":
                    result.errors.append(
                        ValidationIssue(
                            severity="error",
                            code="wrong_zone_extra",
                            message=f"{card.name} cannot be in the Extra Deck.",
                            card_id=card.id,
                            zone="extra",
                        )
                    )
                elif mechanic and mechanic not in rules.allowed_extra_mechanics:
                    result.errors.append(
                        ValidationIssue(
                            severity="error",
                            code="wrong_zone_extra",
                            message=f"{card.name} cannot be in the Extra Deck for this format.",
                            card_id=card.id,
                            zone="extra",
                        )
                    )

        if rules.disallow_link and mechanic == "link":
            result.errors.append(
                ValidationIssue(
                    severity="error",
                    code="link_forbidden",
                    message=f"{card.name} is a Link Monster and is not allowed in this format.",
                    card_id=card.id,
                    zone=dc.zone,
                )
            )

        if rules.disallow_pendulum and mechanic == "pendulum":
            result.errors.append(
                ValidationIssue(
                    severity="error",
                    code="pendulum_forbidden",
                    message=f"{card.name} is a Pendulum Monster and is not allowed in this format.",
                    card_id=card.id,
                    zone=dc.zone,
                )
            )


def _validate_copy_limits(
    rules: FormatRules,
    deck_cards: list[tuple[DeckCard, Card]],
    banlist_map: dict[int, str],
    result: DeckValidation,
) -> None:
    totals: dict[int, int] = defaultdict(int)
    for dc, card in deck_cards:
        totals[card.id] += dc.quantity

    for card_id, total in totals.items():
        status = banlist_map.get(card_id)
        max_copies = effective_max_copies(status, rules)
        if total > max_copies:
            card_name = next(c.name for dc, c in deck_cards if c.id == card_id)
            if max_copies == 0:
                msg = f"{card_name} is Forbidden and cannot be included."
                code = "forbidden"
            elif max_copies == 1:
                msg = f"{card_name} is Limited to 1 copy (you have {total})."
                code = "limited"
            elif max_copies == 2:
                msg = f"{card_name} is Semi-Limited to 2 copies (you have {total})."
                code = "semi_limited"
            else:
                msg = f"{card_name} exceeds the copy limit of {max_copies} (you have {total})."
                code = "copy_limit"
            result.errors.append(
                ValidationIssue(
                    severity="error",
                    code=code,
                    message=msg,
                    card_id=card_id,
                )
            )


def _validate_card_pool(
    session: Session,
    rules: FormatRules,
    deck_cards: list[tuple[DeckCard, Card]],
    result: DeckValidation,
) -> None:
    if not rules.pool_uses_legality_table and not rules.pool_cutoff_date:
        return
    for dc, card in deck_cards:
        if not card_legal_in_format(session, card, rules):
            result.errors.append(
                ValidationIssue(
                    severity="error",
                    code="not_in_pool",
                    message=f"{card.name} is not legal in {rules.name}.",
                    card_id=card.id,
                    zone=dc.zone,
                )
            )


def _validate_point_cap(
    rules: FormatRules,
    deck_cards: list[tuple[DeckCard, Card]],
    points_map: dict[int, int],
    result: DeckValidation,
) -> None:
    if not rules.uses_point_list or rules.point_cap is None:
        return
    total = 0
    for dc, card in deck_cards:
        total += card_point_value(card.id, points_map) * dc.quantity
    result.points_total = total
    result.points_cap = rules.point_cap
    if total > rules.point_cap:
        result.errors.append(
            ValidationIssue(
                severity="error",
                code="point_cap_exceeded",
                message=(
                    f"Deck point total is {total}, which exceeds the cap of {rules.point_cap}."
                ),
            )
        )


def validate_deck(session: Session, deck: Deck) -> DeckValidation:
    rules = get_format_rules(deck.format_code) or get_format_rules("advanced")
    assert rules is not None

    deck_cards = session.execute(
        select(DeckCard, Card)
        .join(Card, DeckCard.card_id == Card.id)
        .where(DeckCard.deck_id == deck.id)
    ).all()
    deck_cards = [(dc, card) for dc, card in deck_cards]

    counts = {"main": 0, "extra": 0, "side": 0}
    for dc, _card in deck_cards:
        counts[dc.zone] = counts.get(dc.zone, 0) + dc.quantity

    result = DeckValidation(
        main_count=counts.get("main", 0),
        extra_count=counts.get("extra", 0),
        side_count=counts.get("side", 0),
        card_count=sum(counts.values()),
    )

    revision = resolve_banlist_revision(session, rules, deck.banlist_revision_id)
    banlist_map = load_banlist_map(session, revision)

    point_list = None
    points_map: dict[int, int] = {}
    if rules.uses_point_list:
        point_list = resolve_genesys_point_list(session, deck.genesys_point_list_id)
        points_map = load_genesys_points_map(session, point_list)

    _validate_deck_sizes(rules, counts, result)
    _validate_zone_placement(rules, deck_cards, result)
    _validate_copy_limits(rules, deck_cards, banlist_map, result)
    _validate_card_pool(session, rules, deck_cards, result)
    _validate_point_cap(rules, deck_cards, points_map, result)

    return result
