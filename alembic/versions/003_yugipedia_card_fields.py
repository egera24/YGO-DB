"""Yugipedia-native card search columns

Revision ID: 003
Revises: 002
Create Date: 2026-06-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cards", sa.Column("category", sa.String(length=16), nullable=True))
    op.add_column("cards", sa.Column("types", sa.Text(), nullable=True))
    op.add_column("cards", sa.Column("mechanic", sa.String(length=64), nullable=True))
    op.add_column("cards", sa.Column("rank", sa.Integer(), nullable=True))
    op.add_column("cards", sa.Column("link_rating", sa.Integer(), nullable=True))
    op.add_column("cards", sa.Column("pendulum_scale", sa.Integer(), nullable=True))
    op.add_column("cards", sa.Column("link_markers", sa.Text(), nullable=True))
    op.add_column("cards", sa.Column("summoning_condition", sa.Text(), nullable=True))

    op.create_index("ix_cards_category", "cards", ["category"], unique=False)
    op.create_index("ix_cards_mechanic", "cards", ["mechanic"], unique=False)
    op.create_index("ix_cards_rank", "cards", ["rank"], unique=False)
    op.create_index("ix_cards_link_rating", "cards", ["link_rating"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_cards_link_rating", table_name="cards")
    op.drop_index("ix_cards_rank", table_name="cards")
    op.drop_index("ix_cards_mechanic", table_name="cards")
    op.drop_index("ix_cards_category", table_name="cards")

    op.drop_column("cards", "summoning_condition")
    op.drop_column("cards", "link_markers")
    op.drop_column("cards", "pendulum_scale")
    op.drop_column("cards", "link_rating")
    op.drop_column("cards", "rank")
    op.drop_column("cards", "mechanic")
    op.drop_column("cards", "types")
    op.drop_column("cards", "category")
