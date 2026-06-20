"""Yugipedia tcg_sets, card errata, and tips columns

Revision ID: 010
Revises: 009
Create Date: 2026-06-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tcg_sets",
        sa.Column("abbr", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("set_type", sa.String(length=128), nullable=True),
        sa.Column("series", sa.String(length=256), nullable=True),
        sa.Column("region", sa.String(length=8), nullable=False, server_default="TCG"),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("abbr"),
    )

    op.add_column(
        "cards",
        sa.Column("has_errata", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("cards", sa.Column("last_erratum_date", sa.Date(), nullable=True))
    op.add_column("cards", sa.Column("tips", sa.Text(), nullable=True))

    op.create_table(
        "card_errata_versions",
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("version_index", sa.Integer(), nullable=False),
        sa.Column("version_label", sa.String(length=64), nullable=False),
        sa.Column("lore_text", sa.Text(), nullable=True),
        sa.Column("set_code", sa.String(length=32), nullable=True),
        sa.Column("set_name", sa.String(length=256), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("card_id", "language", "version_index"),
    )
    op.create_index(
        op.f("ix_card_errata_versions_card_id"),
        "card_errata_versions",
        ["card_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_card_errata_versions_card_id"), table_name="card_errata_versions")
    op.drop_table("card_errata_versions")
    op.drop_column("cards", "tips")
    op.drop_column("cards", "last_erratum_date")
    op.drop_column("cards", "has_errata")
    op.drop_table("tcg_sets")
