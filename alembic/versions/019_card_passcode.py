"""Decouple cards.id (surrogate) from passcode; add passcode + source_url

Revision ID: 019
Revises: 018
Create Date: 2026-07-08

Cards printed without a passcode (Egyptian Gods, tokens, promos) cannot use the
passcode as their primary key. This migration turns ``cards.id`` into an
autoincrement surrogate and adds:

- ``cards.passcode``   real Konami passcode, NULL for passwordless cards (unique)
- ``cards.source_url`` Yugipedia page URL, unique natural key for upsert matching

The catalog is rebuilt by a full reimport after this migration, so no data
backfill or foreign-key remap is required here.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cards", sa.Column("passcode", sa.Integer(), nullable=True))
    op.add_column("cards", sa.Column("source_url", sa.String(length=512), nullable=True))
    op.create_index(op.f("ix_cards_passcode"), "cards", ["passcode"], unique=True)
    op.create_index(op.f("ix_cards_source_url"), "cards", ["source_url"], unique=True)

    # cards.id was originally a plain Integer PK (no sequence). Attach one so new
    # rows autoincrement now that ids are no longer sourced from the passcode.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE SEQUENCE IF NOT EXISTS cards_id_seq OWNED BY cards.id")
        op.execute(
            "SELECT setval('cards_id_seq', "
            "COALESCE((SELECT MAX(id) FROM cards), 0) + 1, false)"
        )
        op.execute("ALTER TABLE cards ALTER COLUMN id SET DEFAULT nextval('cards_id_seq')")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE cards ALTER COLUMN id DROP DEFAULT")
        op.execute("DROP SEQUENCE IF EXISTS cards_id_seq")
    op.drop_index(op.f("ix_cards_source_url"), table_name="cards")
    op.drop_index(op.f("ix_cards_passcode"), table_name="cards")
    op.drop_column("cards", "source_url")
    op.drop_column("cards", "passcode")
