"""Run Alembic migrations and verify schema before catalog import."""

from __future__ import annotations

import json
import sys
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
    postgres_connect_args,
)
from ygo_app.database import engine

_DEBUG_LOG = Path(__file__).resolve().parent.parent / "debug-1305c1.log"

_YUGIPEDIA_DDL = (
    "ALTER TABLE cards ADD COLUMN IF NOT EXISTS category VARCHAR(16)",
    "ALTER TABLE cards ADD COLUMN IF NOT EXISTS types TEXT",
    "ALTER TABLE cards ADD COLUMN IF NOT EXISTS mechanic VARCHAR(64)",
    "ALTER TABLE cards ADD COLUMN IF NOT EXISTS rank INTEGER",
    "ALTER TABLE cards ADD COLUMN IF NOT EXISTS link_rating INTEGER",
    "ALTER TABLE cards ADD COLUMN IF NOT EXISTS pendulum_scale INTEGER",
    "ALTER TABLE cards ADD COLUMN IF NOT EXISTS link_markers TEXT",
    "ALTER TABLE cards ADD COLUMN IF NOT EXISTS summoning_condition TEXT",
    "CREATE INDEX IF NOT EXISTS ix_cards_category ON cards (category)",
    "CREATE INDEX IF NOT EXISTS ix_cards_mechanic ON cards (mechanic)",
    "CREATE INDEX IF NOT EXISTS ix_cards_rank ON cards (rank)",
    "CREATE INDEX IF NOT EXISTS ix_cards_link_rating ON cards (link_rating)",
)


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


def _stderr_diag(label: str, data: dict) -> None:
    """Visible in GitHub Actions logs (no secrets)."""
    print(f"[db_migrate] {label}: {json.dumps(data, default=str)}", file=sys.stderr, flush=True)


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


def _migration_engine(mig_url: str):
    return create_engine(
        mig_url,
        poolclass=pool.NullPool,
        connect_args=postgres_connect_args(mig_url),
    )


def _db_diagnostics(conn) -> dict:
    insp = inspect(conn)
    db_rev = None
    if insp.has_table("alembic_version"):
        db_rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    has_category = False
    cards_schema = None
    if insp.has_table("cards"):
        has_category = conn.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'cards'
                      AND column_name = 'category'
                )
                """
            )
        ).scalar()
        cards_schema = conn.execute(
            text(
                """
                SELECT table_schema FROM information_schema.tables
                WHERE table_name = 'cards'
                ORDER BY CASE WHEN table_schema = current_schema() THEN 0 ELSE 1 END
                LIMIT 1
                """
            )
        ).scalar()
    current_db = conn.execute(text("SELECT current_database()")).scalar()
    return {
        "current_database": current_db,
        "alembic_version": db_rev,
        "cards_schema": cards_schema,
        "has_category_column": bool(has_category),
    }


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


def _apply_yugipedia_columns_idempotent(conn) -> None:
    """Autocommit DDL when Alembic transactional upgrade did not persist."""
    for stmt in _YUGIPEDIA_DDL:
        conn.execute(text(stmt))
    conn.execute(
        text(
            """
            UPDATE alembic_version SET version_num = '003'
            WHERE version_num = '002'
            """
        )
    )
    conn.commit()


def ensure_db_at_head() -> None:
    """Apply pending Alembic revisions; fail fast if Yugipedia columns are still missing."""
    mig_url = database_url_for_migrations()
    entry = {
        "app_url_host": database_host_fingerprint(DATABASE_URL),
        "migration_url_host": database_host_fingerprint(mig_url),
        "urls_differ": mig_url != DATABASE_URL,
    }
    _agent_debug_log(
        hypothesis_id="A,C",
        location="db_migrate.py:ensure_db_at_head:entry",
        message="migration URLs",
        data=entry,
    )
    _stderr_diag("entry", entry)

    engine.dispose()
    mig_engine = _migration_engine(mig_url)
    try:
        with mig_engine.connect() as conn:
            before = {**_revision_state_on(mig_engine), **_db_diagnostics(conn)}
        _stderr_diag("before_upgrade", before)
        _agent_debug_log(
            hypothesis_id="B",
            location="db_migrate.py:ensure_db_at_head:before_upgrade",
            message="schema before upgrade",
            data=before,
        )

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", mig_url)
        command.upgrade(alembic_cfg, "head")

        with mig_engine.connect() as conn:
            after = {**_revision_state_on(mig_engine), **_db_diagnostics(conn)}
        _stderr_diag("after_alembic_upgrade", after)
        _agent_debug_log(
            hypothesis_id="D,E",
            location="db_migrate.py:ensure_db_at_head:after_upgrade",
            message="schema after alembic upgrade",
            data=after,
        )

        state = _revision_state_on(mig_engine)
        if state["missing_yugipedia_columns"]:
            _stderr_diag(
                "alembic_incomplete",
                {"action": "idempotent_ddl_fallback", "missing": state["missing_yugipedia_columns"]},
            )
            with mig_engine.connect() as conn:
                _apply_yugipedia_columns_idempotent(conn)
            state = _revision_state_on(mig_engine)
            with mig_engine.connect() as conn:
                fallback_after = {**state, **_db_diagnostics(conn)}
            _stderr_diag("after_idempotent_fallback", fallback_after)
            _agent_debug_log(
                hypothesis_id="D",
                location="db_migrate.py:ensure_db_at_head:after_fallback",
                message="schema after idempotent DDL",
                data=fallback_after,
                run_id="post-fix",
            )
    finally:
        mig_engine.dispose()

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    repo_head = script.get_current_head()
    state["repo_head"] = repo_head

    if state["missing_yugipedia_columns"]:
        raise RuntimeError(
            "Database schema is missing Yugipedia search columns "
            f"{state['missing_yugipedia_columns']}. "
            f"alembic_version={state['db_revision']!r}, repo head={state['repo_head']!r}. "
            "Set DATABASE_URL_MIGRATIONS to Neon direct URL (host without -pooler) and re-run."
        )

    if state["db_revision"] != state["repo_head"]:
        raise RuntimeError(
            f"alembic_version ({state['db_revision']!r}) does not match repo head "
            f"({state['repo_head']!r}) after upgrade"
        )
