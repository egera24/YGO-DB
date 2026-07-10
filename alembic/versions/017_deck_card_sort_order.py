"""Per-copy deck card ordering with sort_order

Revision ID: 017
Revises: 016
Create Date: 2026-07-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ZONE_ORDER = {"main": 0, "extra": 1, "side": 2}


def _expand_deck_cards_to_per_copy(conn) -> None:
    rows = conn.execute(
        text(
            "SELECT id, deck_id, card_id, zone, quantity "
            "FROM deck_cards ORDER BY deck_id, zone, card_id, id"
        )
    ).fetchall()

    by_deck: dict[int, list] = {}
    for row in rows:
        by_deck.setdefault(row.deck_id, []).append(row)

    conn.execute(text("DELETE FROM deck_cards"))

    for deck_id, deck_rows in by_deck.items():
        deck_rows.sort(
            key=lambda r: (_ZONE_ORDER.get(r.zone, 99), r.card_id, r.id)
        )
        zone_counters = {"main": 0, "extra": 0, "side": 0}
        for row in deck_rows:
            qty = max(int(row.quantity or 1), 1)
            for _ in range(qty):
                sort_order = zone_counters.get(row.zone, 0)
                conn.execute(
                    text(
                        "INSERT INTO deck_cards "
                        "(deck_id, card_id, zone, quantity, sort_order) "
                        "VALUES (:deck_id, :card_id, :zone, 1, :sort_order)"
                    ),
                    {
                        "deck_id": deck_id,
                        "card_id": row.card_id,
                        "zone": row.zone,
                        "sort_order": sort_order,
                    },
                )
                zone_counters[row.zone] = sort_order + 1


def upgrade() -> None:
    op.add_column(
        "deck_cards",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        op.f("ix_deck_cards_sort_order"),
        "deck_cards",
        ["sort_order"],
        unique=False,
    )
    op.drop_constraint("uq_deck_card_zone", "deck_cards", type_="unique")

    conn = op.get_bind()
    _expand_deck_cards_to_per_copy(conn)


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        text(
            "SELECT deck_id, card_id, zone, quantity, sort_order "
            "FROM deck_cards ORDER BY deck_id, zone, sort_order, id"
        )
    ).fetchall()

    aggregated: dict[tuple[int, int, str], int] = {}
    for row in rows:
        key = (row.deck_id, row.card_id, row.zone)
        aggregated[key] = aggregated.get(key, 0) + int(row.quantity or 1)

    conn.execute(text("DELETE FROM deck_cards"))
    for (deck_id, card_id, zone), quantity in aggregated.items():
        conn.execute(
            text(
                "INSERT INTO deck_cards (deck_id, card_id, zone, quantity, sort_order) "
                "VALUES (:deck_id, :card_id, :zone, :quantity, 0)"
            ),
            {
                "deck_id": deck_id,
                "card_id": card_id,
                "zone": zone,
                "quantity": quantity,
            },
        )

    op.drop_index(op.f("ix_deck_cards_sort_order"), table_name="deck_cards")
    op.drop_column("deck_cards", "sort_order")
    op.create_unique_constraint(
        "uq_deck_card_zone",
        "deck_cards",
        ["deck_id", "card_id", "zone"],
    )
