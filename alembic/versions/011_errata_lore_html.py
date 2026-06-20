"""Add lore_html to card_errata_versions

Revision ID: 011
Revises: 010
Create Date: 2026-06-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "card_errata_versions",
        sa.Column("lore_html", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("card_errata_versions", "lore_html")
