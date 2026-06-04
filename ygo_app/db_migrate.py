"""Run Alembic migrations and verify schema before catalog import."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from ygo_app.database import engine

_REQUIRED_CARD_COLUMNS = frozenset(
    {
        "category",
        "types",
        "mechanic",
        "rank",
        "link_rating",
        "pendulum_scale",
        "link_markers",
        "summoning_condition",
    }
)


def _alembic_revision_state() -> dict:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    repo_head = script.get_current_head()
    with engine.connect() as conn:
        db_rev = None
        if inspect(conn).has_table("alembic_version"):
            db_rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        card_cols = (
            {c["name"] for c in inspect(conn).get_columns("cards")}
            if inspect(conn).has_table("cards")
            else set()
        )
    missing = sorted(_REQUIRED_CARD_COLUMNS - card_cols)
    return {
        "repo_head": repo_head,
        "db_revision": db_rev,
        "missing_yugipedia_columns": missing,
    }


def ensure_db_at_head() -> None:
    """Apply pending Alembic revisions; fail fast if Yugipedia columns are still missing."""
    command.upgrade(Config("alembic.ini"), "head")

    state = _alembic_revision_state()
    if state["missing_yugipedia_columns"]:
        raise RuntimeError(
            "Database schema is missing Yugipedia search columns "
            f"{state['missing_yugipedia_columns']}. "
            f"alembic_version={state['db_revision']!r}, repo head={state['repo_head']!r}. "
            "Ensure migration 003 is in the deployed commit and run: alembic upgrade head"
        )

    if state["db_revision"] != state["repo_head"]:
        raise RuntimeError(
            f"alembic_version ({state['db_revision']!r}) does not match repo head "
            f"({state['repo_head']!r}) after upgrade"
        )
