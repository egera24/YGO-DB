"""Format rule definitions and validation issue types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

BanlistMode = Literal["advanced", "traditional", "none"]
ExtraDeckMechanic = Literal["fusion", "synchro", "xyz", "link", "pendulum"]


@dataclass(frozen=True)
class FormatRules:
    code: str
    name: str
    main_min: int | None
    main_max: int | None
    extra_max: int | None
    side_max: int | None
    max_copies_default: int = 3
    banlist_mode: BanlistMode = "none"
    banlist_selectable: bool = False
    fixed_banlist_label: str | None = None
    uses_point_list: bool = False
    point_cap: int | None = None
    allowed_extra_mechanics: frozenset[ExtraDeckMechanic] = frozenset(
        {"fusion", "synchro", "xyz", "link", "pendulum"}
    )
    forbidden_main_mechanics: frozenset[ExtraDeckMechanic] = frozenset(
        {"fusion", "synchro", "xyz", "link"}
    )
    pool_cutoff_date: date | None = None
    pool_uses_legality_table: bool = False
    recommend_main_exact: int | None = None
    disallow_link: bool = False
    disallow_pendulum: bool = False


@dataclass
class ValidationIssue:
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    card_id: int | None = None
    zone: str | None = None


@dataclass
class DeckValidation:
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    info: list[ValidationIssue] = field(default_factory=list)
    main_count: int = 0
    extra_count: int = 0
    side_count: int = 0
    card_count: int = 0
    points_total: int | None = None
    points_cap: int | None = None

    def to_dict(self) -> dict:
        def _issue(issue: ValidationIssue) -> dict:
            payload = {
                "severity": issue.severity,
                "code": issue.code,
                "message": issue.message,
            }
            if issue.card_id is not None:
                payload["card_id"] = issue.card_id
            if issue.zone is not None:
                payload["zone"] = issue.zone
            return payload

        return {
            "errors": [_issue(i) for i in self.errors],
            "warnings": [_issue(i) for i in self.warnings],
            "info": [_issue(i) for i in self.info],
            "main_count": self.main_count,
            "extra_count": self.extra_count,
            "side_count": self.side_count,
            "card_count": self.card_count,
            "points_total": self.points_total,
            "points_cap": self.points_cap,
        }


DECK_ZONE_TOOLTIPS = {
    "main": (
        "The Main Deck is the primary deck you use in a Yu-Gi-Oh! Duel, and it is the deck "
        "you draw cards from during play. It usually contains Monster, Spell, and Trap Cards, "
        "and it forms the main strategy of your deck."
    ),
    "extra": (
        "The Extra Deck is a separate deck used for special monster types that are not kept "
        "in the Main Deck. It typically contains Fusion, Synchro, Xyz, and Link Monsters, "
        "and these monsters are summoned only when specific game conditions are met."
    ),
    "side": (
        "The Side Deck is an optional reserve deck used between Duels in a Match. It lets you "
        "swap cards with your Main Deck and Extra Deck to adapt your strategy against a specific "
        "opponent or matchup."
    ),
}
