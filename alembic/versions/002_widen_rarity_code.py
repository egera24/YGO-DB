"""Widen rarity code columns for long YGOProDeck rarity labels

Revision ID: 002
Revises: 001
Create Date: 2026-06-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "printings",
        "set_rarity_code",
        existing_type=sa.String(length=16),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.alter_column(
        "collection_items",
        "rarity_code",
        existing_type=sa.String(length=16),
        type_=sa.String(length=64),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "collection_items",
        "rarity_code",
        existing_type=sa.String(length=64),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
    op.alter_column(
        "printings",
        "set_rarity_code",
        existing_type=sa.String(length=64),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
