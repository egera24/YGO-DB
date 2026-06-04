"""Run Alembic migrations and verify schema before catalog import."""

from __future__ import annotations

import json
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, pool, text

from ygo_app.config import (
    DATABASE_URL,
    database_host_fingerprint,
    database_url_for_migrations,
)
from ygo_app.database import engine

_DEBUG_LOG = Path(__file__).resolve().parent.parent / "debug-1305c1.log"


def _agent_debug_log(
    *,
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict,
    run_id: str = "pre-fix",
) -> None:
    # region agent log
    payload = {
        "sessionId": "1305c1",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        with _DEBUG_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=str) + "\n")
    except OSError:
        pass
    # endregion

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


def _revision_state_on(bind_engine) -> dict:
    with bind_engine.connect() as conn:
        db_rev = None
        if inspect(conn).has_table("alembic_version"):
            db_rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        card_cols = (
            {c["name"] for c in inspect(conn).get_columns("cards")}
            if inspect(conn).has_table("cards")
            else set()
        )
    missing = sorted(_REQUIRED_CARD_COLUMNS - card_cols)
    return {"db_revision": db_rev, "missing_yugipedia_columns": missing}


def _alembic_revision_state() -> dict:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    repo_head = script.get_current_head()
    state = _revision_state_on(engine)
    return {
        "repo_head": repo_head,
        "db_revision": state["db_revision"],
        "missing_yugipedia_columns": state["missing_yugipedia_columns"],
    }


def ensure_db_at_head() -> None:
    """Apply pending Alembic revisions; fail fast if Yugipedia columns are still missing."""
    mig_url = database_url_for_migrations()
    _agent_debug_log(
        hypothesis_id="A",
        location="db_migrate.py:ensure_db_at_head:entry",
        message="migration URLs",
        data={
            "app_url_host": database_host_fingerprint(DATABASE_URL),
            "migration_url_host": database_host_fingerprint(mig_url),
            "urls_differ": mig_url != DATABASE_URL,
        },
    )
    before_app = _revision_state_on(engine)
    _agent_debug_log(
        hypothesis_id="B",
        location="db_migrate.py:ensure_db_at_head:before_upgrade",
        message="schema via app engine before upgrade",
        data=before_app,
    )

    command.upgrade(Config("alembic.ini"), "head")

    after_app = _revision_state_on(engine)
    mig_engine = create_engine(mig_url, poolclass=pool.NullPool)
    try:
        after_mig = _revision_state_on(mig_engine)
    finally:
        mig_engine.dispose()
    _agent_debug_log(
        hypothesis_id="A,B",
        location="db_migrate.py:ensure_db_at_head:after_upgrade",
        message="schema after upgrade (app vs migration URL)",
        data={"app_engine": after_app, "migration_url_engine": after_mig},
    )

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    repo_head = script.get_current_head()
    verify_engine = create_engine(mig_url, poolclass=pool.NullPool)
    try:
        state = _revision_state_on(verify_engine)
    finally:
        verify_engine.dispose()
    state["repo_head"] = repo_head

    if state["missing_yugipedia_columns"]:
        raise RuntimeError(
            "Database schema is missing Yugipedia search columns "
            f"{state['missing_yugipedia_columns']}. "
            f"alembic_version={state['db_revision']!r}, repo head={state['repo_head']!r}. "
            "Ensure migration 003 is in the deployed commit and run migrations with a "
            "direct Neon URL (not -pooler) or set DATABASE_URL_MIGRATIONS"
        )

    if state["db_revision"] != state["repo_head"]:
        raise RuntimeError(
            f"alembic_version ({state['db_revision']!r}) does not match repo head "
            f"({state['repo_head']!r}) after upgrade"
        )
