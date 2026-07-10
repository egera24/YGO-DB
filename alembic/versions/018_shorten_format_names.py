"""Shorten format display names (Advanced, Traditional, Goat)

Revision ID: 018
Revises: 017
Create Date: 2026-07-08
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RENAMES = [
    ("advanced", "Advanced", "Advanced TCG"),
    ("traditional", "Traditional", "Traditional TCG"),
    ("goat", "Goat", "Goat Format"),
]


def upgrade() -> None:
    conn = op.get_bind()
    for code, new_name, _old_name in _RENAMES:
        conn.execute(
            text("UPDATE formats SET name = :name WHERE code = :code"),
            {"code": code, "name": new_name},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for code, _new_name, old_name in _RENAMES:
        conn.execute(
            text("UPDATE formats SET name = :name WHERE code = :code"),
            {"code": code, "name": old_name},
        )
