"""Add sell_price to collection_items

Revision ID: 012
Revises: 011
Create Date: 2026-06-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collection_items",
        sa.Column("sell_price", sa.Float(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE collection_items SET sell_price = COALESCE(trend_price, 0) "
            "WHERE sell_price IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("collection_items", "sell_price")
