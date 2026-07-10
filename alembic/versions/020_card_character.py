"""Add character column for Skill Cards

Revision ID: 020
Revises: 019
Create Date: 2026-07-10

Skill Cards are associated with a duelist character on Yugipedia. Store the
SMW ``Character`` printout on ``cards.character`` for catalog display/filtering.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cards", sa.Column("character", sa.String(length=128), nullable=True))
    op.create_index(op.f("ix_cards_character"), "cards", ["character"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_cards_character"), table_name="cards")
    op.drop_column("cards", "character")
