"""Registry of all supported game formats."""

from __future__ import annotations

from datetime import date

from ygo_app.formats.base import FormatRules

GOAT_POOL_CUTOFF = date(2005, 2, 24)
EDISON_POOL_CUTOFF = date(2010, 4, 20)

FORMAT_REGISTRY: dict[str, FormatRules] = {
    "advanced": FormatRules(
        code="advanced",
        name="Advanced",
        main_min=40,
        main_max=60,
        extra_max=15,
        side_max=15,
        banlist_mode="advanced",
        banlist_selectable=True,
        recommend_main_exact=40,
    ),
    "traditional": FormatRules(
        code="traditional",
        name="Traditional",
        main_min=40,
        main_max=60,
        extra_max=15,
        side_max=15,
        banlist_mode="traditional",
        banlist_selectable=True,
        recommend_main_exact=40,
    ),
    "edison": FormatRules(
        code="edison",
        name="Edison",
        main_min=40,
        main_max=60,
        extra_max=15,
        side_max=15,
        banlist_mode="advanced",
        banlist_selectable=False,
        fixed_banlist_label="March 2010",
        pool_cutoff_date=EDISON_POOL_CUTOFF,
        pool_uses_legality_table=True,
        recommend_main_exact=40,
    ),
    "goat": FormatRules(
        code="goat",
        name="Goat",
        main_min=40,
        main_max=None,
        extra_max=None,
        side_max=15,
        banlist_mode="advanced",
        banlist_selectable=False,
        fixed_banlist_label="March 2005",
        pool_cutoff_date=GOAT_POOL_CUTOFF,
        pool_uses_legality_table=True,
        allowed_extra_mechanics=frozenset({"fusion"}),
        forbidden_main_mechanics=frozenset({"fusion", "synchro", "xyz", "link"}),
        recommend_main_exact=40,
    ),
    "speed_duel": FormatRules(
        code="speed_duel",
        name="Speed Duel",
        main_min=20,
        main_max=30,
        extra_max=5,
        side_max=6,
        banlist_mode="none",
        pool_uses_legality_table=True,
    ),
    "genesys": FormatRules(
        code="genesys",
        name="Genesys",
        main_min=40,
        main_max=60,
        extra_max=15,
        side_max=15,
        banlist_mode="none",
        uses_point_list=True,
        point_cap=100,
        disallow_link=True,
        disallow_pendulum=True,
        recommend_main_exact=40,
    ),
}


def get_format_rules(code: str) -> FormatRules | None:
    return FORMAT_REGISTRY.get(code)
