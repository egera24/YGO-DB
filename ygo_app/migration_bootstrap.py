"""Stamp Alembic revision when schema was created outside migrations (e.g. init_db/create_all)."""

from __future__ import annotations

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection


def _current_revision(connection: Connection) -> str | None:
    insp = inspect(connection)
    if not insp.has_table("alembic_version"):
        return None
    row = connection.execute(text("SELECT version_num FROM alembic_version")).fetchone()
    return row[0] if row else None


def _printings_rarity_code_length(connection: Connection) -> int | None:
    insp = inspect(connection)
    if not insp.has_table("printings"):
        return None
    for col in insp.get_columns("printings"):
        if col["name"] == "set_rarity_code":
            col_type = col["type"]
            return getattr(col_type, "length", None)
    return None


def _revision_for_legacy_schema(connection: Connection) -> str:
    """Pick stamp target: 001 if rarity columns are still 16-char, else 002 (head)."""
    rarity_len = _printings_rarity_code_length(connection)
    if rarity_len is not None and rarity_len <= 16:
        return "001"
    return "002"


def stamp_legacy_schema_if_needed(connection: Connection, config: Config) -> str | None:
    """
    If tables exist but alembic_version is empty, stamp the matching revision.
    Returns stamped revision id, or None if no stamp was applied.
    """
    current = _current_revision(connection)
    if current:
        return None

    insp = inspect(connection)
    if not insp.has_table("users"):
        return None

    revision = _revision_for_legacy_schema(connection)
    script = ScriptDirectory.from_config(config)
    migration_context = MigrationContext.configure(connection)
    migration_context.stamp(script, revision)
    return revision
