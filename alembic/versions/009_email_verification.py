"""Email verification for registration

Revision ID: 009
Revises: 008
Create Date: 2026-06-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE users SET email_verified_at = created_at")

    op.create_table(
        "pending_registrations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("otp_hash", sa.String(length=64), nullable=False),
        sa.Column("otp_expires_at", sa.DateTime(), nullable=False),
        sa.Column("otp_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(
        op.f("ix_pending_registrations_email"),
        "pending_registrations",
        ["email"],
        unique=True,
    )

    op.create_table(
        "auth_rate_limits",
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("auth_rate_limits")
    op.drop_index(op.f("ix_pending_registrations_email"), table_name="pending_registrations")
    op.drop_table("pending_registrations")
    op.drop_column("users", "email_verified_at")
