"""Trade order locks and locked_quantity on collection items

Revision ID: 024
Revises: 023
Create Date: 2026-07-24
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("collection_items", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("locked_quantity", sa.Integer(), nullable=False, server_default="0")
        )

    op.create_table(
        "trade_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("buyer_name", sa.String(length=128), nullable=True),
        sa.Column("buyer_email", sa.String(length=255), nullable=True),
        sa.Column("buyer_phone", sa.String(length=64), nullable=True),
        sa.Column("buyer_address", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trade_orders_user_id", "trade_orders", ["user_id"], unique=False)
    op.create_index(
        "ix_trade_orders_created_at", "trade_orders", ["created_at"], unique=False
    )

    op.create_table(
        "trade_order_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("collection_item_id", sa.Integer(), nullable=True),
        sa.Column("card_name", sa.String(length=256), nullable=True),
        sa.Column("set_code", sa.String(length=32), nullable=False),
        sa.Column("set_name", sa.String(length=256), nullable=True),
        sa.Column("rarity_code", sa.String(length=64), nullable=False),
        sa.Column("rarity_display", sa.String(length=64), nullable=True),
        sa.Column("condition", sa.String(length=32), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column("offer_price", sa.Float(), nullable=True),
        sa.Column("list_price", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["trade_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["collection_item_id"],
            ["collection_items.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trade_order_lines_order_id", "trade_order_lines", ["order_id"], unique=False
    )
    op.create_index(
        "ix_trade_order_lines_collection_item_id",
        "trade_order_lines",
        ["collection_item_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_trade_order_lines_collection_item_id", table_name="trade_order_lines")
    op.drop_index("ix_trade_order_lines_order_id", table_name="trade_order_lines")
    op.drop_table("trade_order_lines")
    op.drop_index("ix_trade_orders_created_at", table_name="trade_orders")
    op.drop_index("ix_trade_orders_user_id", table_name="trade_orders")
    op.drop_table("trade_orders")
    with op.batch_alter_table("collection_items", schema=None) as batch_op:
        batch_op.drop_column("locked_quantity")
