"""Printing market prices + Cardmarket expansion cache

Revision ID: 007
Revises: 006
Create Date: 2026-06-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "printing_market_prices",
        sa.Column("set_code", sa.String(32), primary_key=True),
        sa.Column("rarity_code", sa.String(64), primary_key=True),
        sa.Column("cardmarket_product_id", sa.Integer(), nullable=True),
        sa.Column("cardmarket_url", sa.String(512), nullable=True),
        sa.Column("low_price", sa.Float(), nullable=True),
        sa.Column("avg_price", sa.Float(), nullable=True),
        sa.Column("trend_price", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="EUR"),
        sa.Column("discovery_status", sa.String(16), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_printing_market_prices_updated_at",
        "printing_market_prices",
        ["updated_at"],
    )

    op.create_table(
        "cardmarket_expansions",
        sa.Column("expansion_id", sa.Integer(), primary_key=True),
        sa.Column("expansion_code", sa.String(32), nullable=True),
        sa.Column("expansion_name", sa.String(256), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_cardmarket_expansions_expansion_code",
        "cardmarket_expansions",
        ["expansion_code"],
    )


def downgrade() -> None:
    op.drop_index("ix_cardmarket_expansions_expansion_code", table_name="cardmarket_expansions")
    op.drop_table("cardmarket_expansions")
    op.drop_index("ix_printing_market_prices_updated_at", table_name="printing_market_prices")
    op.drop_table("printing_market_prices")
