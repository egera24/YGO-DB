"""Initial multi-user schema

Revision ID: 001
Revises:
Create Date: 2026-06-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "cards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=True),
        sa.Column("human_readable_type", sa.String(length=128), nullable=True),
        sa.Column("frame_type", sa.String(length=32), nullable=True),
        sa.Column("desc", sa.Text(), nullable=True),
        sa.Column("atk", sa.Integer(), nullable=True),
        sa.Column("def", sa.Integer(), nullable=True),
        sa.Column("level", sa.Integer(), nullable=True),
        sa.Column("race", sa.String(length=64), nullable=True),
        sa.Column("attribute", sa.String(length=32), nullable=True),
        sa.Column("archetype", sa.String(length=128), nullable=True),
        sa.Column("linkval", sa.Integer(), nullable=True),
        sa.Column("scale", sa.Integer(), nullable=True),
        sa.Column("ygoprodeck_url", sa.String(length=512), nullable=True),
        sa.Column("image_url", sa.String(length=512), nullable=True),
        sa.Column("image_url_small", sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cards_name", "cards", ["name"], unique=False)
    op.create_index("ix_cards_type", "cards", ["type"], unique=False)
    op.create_index("ix_cards_frame_type", "cards", ["frame_type"], unique=False)
    op.create_index("ix_cards_race", "cards", ["race"], unique=False)
    op.create_index("ix_cards_attribute", "cards", ["attribute"], unique=False)
    op.create_index("ix_cards_archetype", "cards", ["archetype"], unique=False)

    op.create_table(
        "printings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("set_name", sa.String(length=256), nullable=True),
        sa.Column("set_code", sa.String(length=32), nullable=False),
        sa.Column("set_rarity", sa.String(length=64), nullable=True),
        sa.Column("set_rarity_code", sa.String(length=16), nullable=False),
        sa.Column("set_price", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("card_id", "set_code", "set_rarity_code", name="uq_printing"),
    )
    op.create_index("ix_printings_card_id", "printings", ["card_id"], unique=False)
    op.create_index("ix_printings_set_code", "printings", ["set_code"], unique=False)
    op.create_index("ix_printings_set_rarity_code", "printings", ["set_rarity_code"], unique=False)

    op.create_table(
        "collection_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("set_code", sa.String(length=32), nullable=False),
        sa.Column("rarity_code", sa.String(length=16), nullable=False),
        sa.Column("card_name", sa.String(length=256), nullable=True),
        sa.Column("expansion_code", sa.String(length=32), nullable=True),
        sa.Column("set_name", sa.String(length=256), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("trade_quantity", sa.Integer(), nullable=True),
        sa.Column("condition", sa.String(length=32), nullable=True),
        sa.Column("edition", sa.String(length=32), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("folder_name", sa.String(length=128), nullable=True),
        sa.Column("price_bought", sa.Float(), nullable=True),
        sa.Column("date_bought", sa.String(length=32), nullable=True),
        sa.Column("avg_price", sa.Float(), nullable=True),
        sa.Column("low_price", sa.Float(), nullable=True),
        sa.Column("trend_price", sa.Float(), nullable=True),
        sa.Column("printing_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["printing_id"], ["printings.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collection_items_user_id", "collection_items", ["user_id"], unique=False)
    op.create_index("ix_collection_items_set_code", "collection_items", ["set_code"], unique=False)
    op.create_index("ix_collection_items_folder_name", "collection_items", ["folder_name"], unique=False)

    op.create_table(
        "user_favorites",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "card_id", name="uq_user_favorite"),
    )
    op.create_index("ix_user_favorites_user_id", "user_favorites", ["user_id"], unique=False)
    op.create_index("ix_user_favorites_card_id", "user_favorites", ["card_id"], unique=False)

    op.create_table(
        "user_card_tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("tag", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "card_id", "tag", name="uq_user_card_tag"),
    )
    op.create_index("ix_user_card_tags_user_id", "user_card_tags", ["user_id"], unique=False)
    op.create_index("ix_user_card_tags_card_id", "user_card_tags", ["card_id"], unique=False)
    op.create_index("ix_user_card_tags_tag", "user_card_tags", ["tag"], unique=False)

    op.create_table(
        "decks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decks_user_id", "decks", ["user_id"], unique=False)
    op.create_index("ix_decks_name", "decks", ["name"], unique=False)

    op.create_table(
        "deck_cards",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("deck_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("zone", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deck_id"], ["decks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deck_id", "card_id", "zone", name="uq_deck_card_zone"),
    )
    op.create_index("ix_deck_cards_deck_id", "deck_cards", ["deck_id"], unique=False)
    op.create_index("ix_deck_cards_card_id", "deck_cards", ["card_id"], unique=False)
    op.create_index("ix_deck_cards_zone", "deck_cards", ["zone"], unique=False)


def downgrade() -> None:
    op.drop_table("deck_cards")
    op.drop_table("decks")
    op.drop_table("user_card_tags")
    op.drop_table("user_favorites")
    op.drop_table("collection_items")
    op.drop_table("printings")
    op.drop_table("cards")
    op.drop_table("users")
