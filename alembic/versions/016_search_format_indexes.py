"""Search and format-pool performance indexes

Revision ID: 016
Revises: 015
Create Date: 2026-07-07
"""
from typing import Sequence, Union

from alembic import op

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_card_format_legality_pool "
        "ON card_format_legality (format_code, is_legal, card_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_genesys_point_entries_list_points "
        "ON genesys_point_entries (list_id, points, card_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_collection_items_user_set_rarity "
        "ON collection_items (user_id, set_code, rarity_code)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tcg_sets_release_date "
        "ON tcg_sets (release_date)"
    )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_tcg_sets_release_date")
    op.execute("DROP INDEX IF EXISTS ix_collection_items_user_set_rarity")
    op.execute("DROP INDEX IF EXISTS ix_genesys_point_entries_list_points")
    op.execute("DROP INDEX IF EXISTS ix_card_format_legality_pool")
