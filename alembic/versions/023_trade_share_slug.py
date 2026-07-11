"""Trade share slug and display name on users

Revision ID: 023
Revises: 022
Create Date: 2026-07-11
"""
from __future__ import annotations

import secrets
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _generate_slug() -> str:
    return secrets.token_urlsafe(16)


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("trade_share_slug", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("trade_display_name", sa.String(length=128), nullable=True))

    conn = op.get_bind()
    users = conn.execute(sa.text("SELECT id FROM users WHERE trade_share_slug IS NULL")).fetchall()
    used: set[str] = set(
        row[0]
        for row in conn.execute(
            sa.text("SELECT trade_share_slug FROM users WHERE trade_share_slug IS NOT NULL")
        ).fetchall()
    )
    for (user_id,) in users:
        for _ in range(30):
            slug = _generate_slug()
            if slug not in used:
                used.add(slug)
                conn.execute(
                    sa.text("UPDATE users SET trade_share_slug = :slug WHERE id = :id"),
                    {"slug": slug, "id": user_id},
                )
                break
        else:
            raise RuntimeError(f"Could not assign trade slug for user {user_id}")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("trade_share_slug", existing_type=sa.String(length=64), nullable=False)
        batch_op.create_index("ix_users_trade_share_slug", ["trade_share_slug"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index("ix_users_trade_share_slug")
        batch_op.drop_column("trade_display_name")
        batch_op.drop_column("trade_share_slug")
