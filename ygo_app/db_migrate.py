"""Run Alembic migrations and verify schema before catalog import."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, pool, text

from ygo_app.config import database_url_for_migrations, postgres_connect_args
from ygo_app.database import engine

# Revision 003 DDL — applied idempotently when Alembic upgrade does not persist (Neon).
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
    """Apply migration 003 DDL with explicit commit (Neon + Alembic may not persist upgrade)."""
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
    """Apply pending Alembic revisions; ensure Yugipedia search columns exist."""
    mig_url = database_url_for_migrations()
    engine.dispose()
    mig_engine = _migration_engine(mig_url)
    try:
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", mig_url)
        command.upgrade(alembic_cfg, "head")

        state = _revision_state_on(mig_engine)
        if state["missing_yugipedia_columns"]:
            with mig_engine.connect() as conn:
                _apply_yugipedia_columns_idempotent(conn)
            state = _revision_state_on(mig_engine)
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
            "Set DATABASE_URL_MIGRATIONS to a Neon direct URL (host without -pooler) and re-run."
        )

    if state["db_revision"] != state["repo_head"]:
        raise RuntimeError(
            f"alembic_version ({state['db_revision']!r}) does not match repo head "
            f"({state['repo_head']!r}) after upgrade"
        )
