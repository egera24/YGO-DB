"""Rarity price ranks + SCD Type 2 printing_market_prices

Revision ID: 014
Revises: 013
Create Date: 2026-06-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RARITY_ROWS = [
    (1, "Common", "C"),
    (2, "Normal Rare", "N"),
    (3, "Short Print", "SP"),
    (4, "Super Short Print", "SSP"),
    (5, "Normal Parallel Rare (Parallel Common)", "NPR"),
    (6, "Duel Terminal Normal Parallel Rare", "DNPR"),
    (7, "Rare", "R"),
    (8, "Duel Terminal Normal Rare Parallel Rare", "DNRPR"),
    (9, "Duel Terminal Rare Parallel Rare", "DRPR"),
    (10, "Super Rare", "SR"),
    (11, "Holofoil Rare", "HFR"),
    (12, "Super Parallel Rare", "SPR"),
    (13, "Duel Terminal Super Parallel Rare", "DSPR"),
    (14, "Starfoil Rare", "SFR"),
    (15, "Mosaic Rare", "MSR"),
    (16, "Shatterfoil Rare", "SHR"),
    (17, "Millennium Rare", "MR"),
    (18, "Ultra Rare", "UR"),
    (19, "Ultra Parallel Rare", "UPR"),
    (20, "Duel Terminal Ultra Parallel Rare", "DUPR"),
    (21, "Gold Rare", "GUR"),
    (22, "Ultimate Rare", "UtR"),
    (23, "Secret Rare", "ScR"),
    (24, "Ultra Secret Rare", "UScR"),
    (25, "Secret Ultra Rare", "ScUR"),
    (26, "Duel Terminal Secret Parallel Rare", "DScPR"),
    (27, "Gold Secret Rare", "GScR"),
    (28, "Ghost/Gold Rare", "GGR"),
    (29, "Premium Gold Rare", "PGR"),
    (30, "Platinum Rare", "PL"),
    (31, "Collector's Rare", "CR"),
    (32, "Ultra Rare (Pharaoh's Rare)", "UR(PR)"),
    (33, "Ghost Rare", "GR"),
    (34, "Starlight Rare", "SLR"),
    (35, "Prismatic Collector's Rare", "CR"),
    (36, "Prismatic Ultimate Rare", "UtR"),
    (37, "Platinum Secret Rare", "PlScR"),
    (38, "Extra Secret Rare", "EXSE"),
    (39, "10000 Secret Rare", "10000 SE"),
    (40, "Prismatic Secret Rare", "PScR"),
    (41, "Quarter Century Secret Rare", "QCSR"),
    (42, "Grand Master Rare", "GMR"),
]


def upgrade() -> None:
    op.create_table(
        "rarity_price_ranks",
        sa.Column("sort_order", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("rarity_code", sa.String(32), nullable=True),
    )
    op.bulk_insert(
        sa.table(
            "rarity_price_ranks",
            sa.column("sort_order", sa.Integer),
            sa.column("name", sa.String),
            sa.column("rarity_code", sa.String),
        ),
        [
            {"sort_order": order, "name": name, "rarity_code": code}
            for order, name, code in RARITY_ROWS
        ],
    )

    op.create_table(
        "printing_market_prices_scd",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("set_code", sa.String(32), nullable=False),
        sa.Column("rarity_code", sa.String(64), nullable=False),
        sa.Column("cardmarket_product_id", sa.Integer(), nullable=True),
        sa.Column("cardmarket_url", sa.String(512), nullable=True),
        sa.Column("low_price", sa.Float(), nullable=True),
        sa.Column("avg_price", sa.Float(), nullable=True),
        sa.Column("trend_price", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="EUR"),
        sa.Column("discovery_status", sa.String(16), nullable=True),
        sa.Column("valid_from", sa.DateTime(), nullable=False),
        sa.Column("valid_to", sa.DateTime(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source_run_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_printing_market_prices_scd_set_code",
        "printing_market_prices_scd",
        ["set_code"],
    )
    op.create_index(
        "ix_printing_market_prices_scd_rarity_code",
        "printing_market_prices_scd",
        ["rarity_code"],
    )
    op.create_index(
        "ix_printing_market_prices_scd_is_current",
        "printing_market_prices_scd",
        ["is_current"],
    )

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT set_code, rarity_code, cardmarket_product_id, cardmarket_url,
                   low_price, avg_price, trend_price, currency, discovery_status, updated_at
            FROM printing_market_prices
            """
        )
    ).fetchall()
    for row in rows:
        conn.execute(
            sa.text(
                """
                INSERT INTO printing_market_prices_scd (
                    set_code, rarity_code, cardmarket_product_id, cardmarket_url,
                    low_price, avg_price, trend_price, currency, discovery_status,
                    valid_from, valid_to, is_current, source_run_id
                ) VALUES (
                    :set_code, :rarity_code, :cardmarket_product_id, :cardmarket_url,
                    :low_price, :avg_price, :trend_price, :currency, :discovery_status,
                    COALESCE(:valid_from, CURRENT_TIMESTAMP), NULL, true, 'migration-014'
                )
                """
            ),
            {
                "set_code": row.set_code,
                "rarity_code": row.rarity_code,
                "cardmarket_product_id": row.cardmarket_product_id,
                "cardmarket_url": row.cardmarket_url,
                "low_price": row.low_price,
                "avg_price": row.avg_price,
                "trend_price": row.trend_price,
                "currency": row.currency or "EUR",
                "discovery_status": row.discovery_status,
                "valid_from": row.updated_at,
            },
        )

    op.drop_index("ix_printing_market_prices_updated_at", table_name="printing_market_prices")
    op.drop_table("printing_market_prices")
    op.rename_table("printing_market_prices_scd", "printing_market_prices")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_index(
            "ix_printing_market_prices_current_key",
            "printing_market_prices",
            ["set_code", "rarity_code"],
            unique=True,
            postgresql_where=sa.text("is_current = true"),
        )
    else:
        op.create_index(
            "ix_printing_market_prices_current_key",
            "printing_market_prices",
            ["set_code", "rarity_code"],
            unique=True,
            sqlite_where=sa.text("is_current = 1"),
        )


def downgrade() -> None:
    op.drop_index("ix_printing_market_prices_current_key", table_name="printing_market_prices")
    op.create_table(
        "printing_market_prices_legacy",
        sa.Column("set_code", sa.String(32), primary_key=True),
        sa.Column("rarity_code", sa.String(64), primary_key=True),
        sa.Column("cardmarket_product_id", sa.Integer(), nullable=True),
        sa.Column("cardmarket_url", sa.String(512), nullable=True),
        sa.Column("low_price", sa.Float(), nullable=True),
        sa.Column("avg_price", sa.Float(), nullable=True),
        sa.Column("trend_price", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="EUR"),
        sa.Column("discovery_status", sa.String(16), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT set_code, rarity_code, cardmarket_product_id, cardmarket_url,
                   low_price, avg_price, trend_price, currency, discovery_status, valid_from
            FROM printing_market_prices
            WHERE is_current = true
            """
        )
    ).fetchall()
    for row in rows:
        conn.execute(
            sa.text(
                """
                INSERT INTO printing_market_prices_legacy (
                    set_code, rarity_code, cardmarket_product_id, cardmarket_url,
                    low_price, avg_price, trend_price, currency, discovery_status, updated_at
                ) VALUES (
                    :set_code, :rarity_code, :cardmarket_product_id, :cardmarket_url,
                    :low_price, :avg_price, :trend_price, :currency, :discovery_status, :updated_at
                )
                """
            ),
            {
                "set_code": row.set_code,
                "rarity_code": row.rarity_code,
                "cardmarket_product_id": row.cardmarket_product_id,
                "cardmarket_url": row.cardmarket_url,
                "low_price": row.low_price,
                "avg_price": row.avg_price,
                "trend_price": row.trend_price,
                "currency": row.currency or "EUR",
                "discovery_status": row.discovery_status,
                "updated_at": row.valid_from,
            },
        )
    op.drop_table("printing_market_prices")
    op.rename_table("printing_market_prices_legacy", "printing_market_prices")
    op.create_index(
        "ix_printing_market_prices_updated_at",
        "printing_market_prices",
        ["updated_at"],
    )
    op.drop_table("rarity_price_ranks")
