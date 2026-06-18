"""Deck preview cover card

Revision ID: 008
Revises: 007
Create Date: 2026-06-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("decks") as batch_op:
        batch_op.add_column(sa.Column("preview_card_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_decks_preview_card_id_cards",
            "cards",
            ["preview_card_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("decks") as batch_op:
        batch_op.drop_constraint("fk_decks_preview_card_id_cards", type_="foreignkey")
        batch_op.drop_column("preview_card_id")
