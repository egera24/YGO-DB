"""Drop denormalized market price columns from collection_items

Revision ID: 013
Revises: 012
Create Date: 2026-06-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("collection_items", "avg_price")
    op.drop_column("collection_items", "low_price")
    op.drop_column("collection_items", "trend_price")


def downgrade() -> None:
    op.add_column("collection_items", sa.Column("trend_price", sa.Float(), nullable=True))
    op.add_column("collection_items", sa.Column("low_price", sa.Float(), nullable=True))
    op.add_column("collection_items", sa.Column("avg_price", sa.Float(), nullable=True))
