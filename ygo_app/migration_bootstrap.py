"""Stamp Alembic revision when schema was created outside migrations (e.g. init_db/create_all)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

_DEBUG_LOG = Path(__file__).resolve().parent.parent / "debug-10d409.log"
_SESSION_ID = "10d409"


def _debug_log(hypothesis_id: str, message: str, data: dict[str, Any]) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": _SESSION_ID,
            "hypothesisId": hypothesis_id,
            "location": "migration_bootstrap.py",
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with _DEBUG_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except OSError:
        pass
    # #endregion


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
    insp = inspect(connection)
    current = _current_revision(connection)
    has_users = insp.has_table("users")

    _debug_log(
        "H2",
        "alembic_bootstrap_check",
        {
            "current_revision": current,
            "has_users": has_users,
            "has_alembic_version": insp.has_table("alembic_version"),
        },
    )

    if current:
        return None

    if not has_users:
        _debug_log("H3", "fresh_db_skip_stamp", {})
        return None

    revision = _revision_for_legacy_schema(connection)
    rarity_len = _printings_rarity_code_length(connection)

    _debug_log(
        "H1",
        "stamping_legacy_schema",
        {"revision": revision, "rarity_code_length": rarity_len},
    )

    script = ScriptDirectory.from_config(config)
    migration_context = MigrationContext.configure(connection)
    migration_context.stamp(script, revision)
    return revision
