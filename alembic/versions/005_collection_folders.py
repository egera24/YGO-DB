"""Collection folders and per-folder quantity allocations

Revision ID: 005
Revises: 004
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _folder_name_key(name: str) -> str:
    return name.strip().lower()


def upgrade() -> None:
    op.create_table(
        "collection_folders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("name_key", sa.String(length=128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name_key", name="uq_collection_folder_user_name"),
    )
    op.create_index(
        op.f("ix_collection_folders_user_id"),
        "collection_folders",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_collection_folders_name_key"),
        "collection_folders",
        ["name_key"],
        unique=False,
    )

    op.create_table(
        "collection_item_folders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("collection_item_id", sa.Integer(), nullable=False),
        sa.Column("folder_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["collection_item_id"], ["collection_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["folder_id"], ["collection_folders.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "collection_item_id",
            "folder_id",
            name="uq_collection_item_folder",
        ),
    )
    op.create_index(
        op.f("ix_collection_item_folders_collection_item_id"),
        "collection_item_folders",
        ["collection_item_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_collection_item_folders_folder_id"),
        "collection_item_folders",
        ["folder_id"],
        unique=False,
    )

    conn = op.get_bind()

    folder_rows = conn.execute(
        sa.text(
            """
            SELECT DISTINCT user_id, TRIM(folder_name) AS name
            FROM collection_items
            WHERE folder_name IS NOT NULL AND TRIM(folder_name) != ''
            """
        )
    ).fetchall()

    folder_id_by_user_key: dict[tuple[int, str], int] = {}
    for user_id, name in folder_rows:
        key = _folder_name_key(name)
        if not key or key == "no folder":
            continue
        existing = folder_id_by_user_key.get((user_id, key))
        if existing is not None:
            continue
        conn.execute(
            sa.text(
                """
                INSERT INTO collection_folders (user_id, name, name_key, sort_order, created_at)
                VALUES (:user_id, :name, :name_key, 0, CURRENT_TIMESTAMP)
                """
            ),
            {"user_id": user_id, "name": name.strip(), "name_key": key},
        )
        folder_id = conn.execute(
            sa.text(
                """
                SELECT id FROM collection_folders
                WHERE user_id = :user_id AND name_key = :name_key
                """
            ),
            {"user_id": user_id, "name_key": key},
        ).scalar_one()
        folder_id_by_user_key[(user_id, key)] = folder_id

    items = conn.execute(
        sa.text(
            """
            SELECT id, user_id, quantity, folder_name
            FROM collection_items
            """
        )
    ).fetchall()

    for item_id, user_id, quantity, folder_name in items:
        folder_id = None
        if folder_name and folder_name.strip():
            key = _folder_name_key(folder_name)
            if key and key != "no folder":
                folder_id = folder_id_by_user_key.get((user_id, key))
        conn.execute(
            sa.text(
                """
                INSERT INTO collection_item_folders
                    (collection_item_id, folder_id, quantity)
                VALUES (:item_id, :folder_id, :quantity)
                """
            ),
            {"item_id": item_id, "folder_id": folder_id, "quantity": quantity or 1},
        )

    op.drop_index("ix_collection_items_folder_name", table_name="collection_items")
    op.drop_column("collection_items", "folder_name")


def downgrade() -> None:
    op.add_column(
        "collection_items",
        sa.Column("folder_name", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_collection_items_folder_name",
        "collection_items",
        ["folder_name"],
        unique=False,
    )

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT cif.collection_item_id, cf.name
            FROM collection_item_folders cif
            LEFT JOIN collection_folders cf ON cf.id = cif.folder_id
            WHERE cif.folder_id IS NOT NULL
            ORDER BY cif.collection_item_id, cif.id
            """
        )
    ).fetchall()
    seen: set[int] = set()
    for item_id, name in rows:
        if item_id in seen:
            continue
        seen.add(item_id)
        conn.execute(
            sa.text(
                "UPDATE collection_items SET folder_name = :name WHERE id = :item_id"
            ),
            {"name": name, "item_id": item_id},
        )

    op.drop_index(
        op.f("ix_collection_item_folders_folder_id"),
        table_name="collection_item_folders",
    )
    op.drop_index(
        op.f("ix_collection_item_folders_collection_item_id"),
        table_name="collection_item_folders",
    )
    op.drop_table("collection_item_folders")
    op.drop_index(op.f("ix_collection_folders_name_key"), table_name="collection_folders")
    op.drop_index(op.f("ix_collection_folders_user_id"), table_name="collection_folders")
    op.drop_table("collection_folders")
