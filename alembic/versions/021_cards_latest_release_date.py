"""Add denormalized latest_release_date on cards for fast search sort

Revision ID: 021
Revises: 020
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cards", sa.Column("latest_release_date", sa.Date(), nullable=True))
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute(
            """
            UPDATE cards c
            SET latest_release_date = sub.max_date
            FROM (
                SELECT p.card_id, MAX(t.release_date) AS max_date
                FROM printings p
                JOIN tcg_sets t ON t.abbr = UPPER(SPLIT_PART(p.set_code, '-', 1))
                WHERE t.release_date IS NOT NULL
                GROUP BY p.card_id
            ) sub
            WHERE c.id = sub.card_id
            """
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cards_latest_release_date "
            "ON cards (latest_release_date)"
        )
    else:
        from sqlalchemy.orm import Session

        from ygo_app.release_dates import refresh_card_latest_release_dates

        session = Session(bind=conn)
        try:
            refresh_card_latest_release_dates(session)
            session.commit()
        finally:
            session.close()


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_cards_latest_release_date")
    op.drop_column("cards", "latest_release_date")
