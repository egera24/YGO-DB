"""Formats, banlists, Genesys point lists, deck format columns

Revision ID: 015
Revises: 014
Create Date: 2026-07-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FORMAT_ROWS = [
    (
        "advanced",
        "Advanced TCG",
        "Official modern tournament format using the current Forbidden, Limited, and Semi-Limited lists.",
        True,
        False,
        1,
    ),
    (
        "traditional",
        "Traditional TCG",
        "Like Advanced, but cards on the Forbidden list are allowed at 1 copy instead of 0.",
        True,
        False,
        2,
    ),
    (
        "edison",
        "Edison",
        "Retro fan format based on Yu-Gi-Oh! around March 2010 (March 2010 banlist, card pool through Duelist Pack: Kaiba).",
        True,
        False,
        3,
    ),
    (
        "goat",
        "Goat Format",
        "Summer 2005 format using the April 2005 banlist and card pool through The Lost Millennium.",
        True,
        False,
        4,
    ),
    (
        "speed_duel",
        "Speed Duel",
        "Simplified official format with a reduced card pool and no banlist.",
        False,
        False,
        5,
    ),
    (
        "genesys",
        "Genesys",
        "Point-based format: deck total must stay within the event point cap (usually 100).",
        False,
        True,
        6,
    ),
]


def upgrade() -> None:
    op.create_table(
        "formats",
        sa.Column("code", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("uses_banlist", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("uses_point_list", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "banlist_revisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_list_id", sa.String(32), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("source_url", sa.String(512), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source_list_id", name="uq_banlist_revision_source_list_id"),
    )
    op.create_index("ix_banlist_revisions_effective_from", "banlist_revisions", ["effective_from"])

    op.create_table(
        "banlist_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "revision_id",
            sa.Integer(),
            sa.ForeignKey("banlist_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("card_id", sa.Integer(), sa.ForeignKey("cards.id", ondelete="SET NULL"), nullable=True),
        sa.Column("card_name_raw", sa.String(256), nullable=False),
        sa.Column("konami_cid", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.UniqueConstraint("revision_id", "card_name_raw", name="uq_banlist_entry_revision_name"),
    )
    op.create_index("ix_banlist_entries_revision_id", "banlist_entries", ["revision_id"])
    op.create_index("ix_banlist_entries_card_id", "banlist_entries", ["card_id"])

    op.create_table(
        "genesys_point_lists",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("source_url", sa.String(512), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("source_url", name="uq_genesys_point_list_source_url"),
    )
    op.create_index("ix_genesys_point_lists_effective_from", "genesys_point_lists", ["effective_from"])

    op.create_table(
        "genesys_point_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "list_id",
            sa.Integer(),
            sa.ForeignKey("genesys_point_lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("card_id", sa.Integer(), sa.ForeignKey("cards.id", ondelete="SET NULL"), nullable=True),
        sa.Column("card_name_raw", sa.String(256), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.UniqueConstraint("list_id", "card_name_raw", name="uq_genesys_point_entry_list_name"),
    )
    op.create_index("ix_genesys_point_entries_list_id", "genesys_point_entries", ["list_id"])
    op.create_index("ix_genesys_point_entries_card_id", "genesys_point_entries", ["card_id"])

    op.create_table(
        "card_format_legality",
        sa.Column("card_id", sa.Integer(), sa.ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "format_code",
            sa.String(32),
            sa.ForeignKey("formats.code", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("is_legal", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("ix_card_format_legality_format_code", "card_format_legality", ["format_code"])

    formats_table = sa.table(
        "formats",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("uses_banlist", sa.Boolean),
        sa.column("uses_point_list", sa.Boolean),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(
        formats_table,
        [
            {
                "code": code,
                "name": name,
                "description": description,
                "uses_banlist": uses_banlist,
                "uses_point_list": uses_point_list,
                "sort_order": sort_order,
            }
            for code, name, description, uses_banlist, uses_point_list, sort_order in FORMAT_ROWS
        ],
    )

    op.add_column(
        "decks",
        sa.Column(
            "format_code",
            sa.String(32),
            sa.ForeignKey("formats.code"),
            nullable=False,
            server_default="advanced",
        ),
    )
    op.add_column(
        "decks",
        sa.Column(
            "banlist_revision_id",
            sa.Integer(),
            sa.ForeignKey("banlist_revisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "decks",
        sa.Column(
            "genesys_point_list_id",
            sa.Integer(),
            sa.ForeignKey("genesys_point_lists.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("decks", "genesys_point_list_id")
    op.drop_column("decks", "banlist_revision_id")
    op.drop_column("decks", "format_code")
    op.drop_table("card_format_legality")
    op.drop_table("genesys_point_entries")
    op.drop_table("genesys_point_lists")
    op.drop_table("banlist_entries")
    op.drop_table("banlist_revisions")
    op.drop_table("formats")
