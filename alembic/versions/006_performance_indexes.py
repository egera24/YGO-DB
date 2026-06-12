"""Performance indexes: pg_trgm text search + collection_items

Revision ID: 006
Revises: 005
Create Date: 2026-06-13

"""
from typing import Sequence, Union

from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cards_name_trgm "
        "ON cards USING gin (name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cards_desc_trgm "
        'ON cards USING gin ("desc" gin_trgm_ops)'
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cards_archetype_trgm "
        "ON cards USING gin (archetype gin_trgm_ops)"
    )
    op.create_index(
        "ix_collection_items_rarity_code",
        "collection_items",
        ["rarity_code"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_collection_items_printing_id",
        "collection_items",
        ["printing_id"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    op.drop_index("ix_collection_items_printing_id", table_name="collection_items")
    op.drop_index("ix_collection_items_rarity_code", table_name="collection_items")
    op.execute("DROP INDEX IF EXISTS ix_cards_archetype_trgm")
    op.execute("DROP INDEX IF EXISTS ix_cards_desc_trgm")
    op.execute("DROP INDEX IF EXISTS ix_cards_name_trgm")
