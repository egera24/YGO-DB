from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from ygo_app.config import database_url_for_migrations, postgres_connect_args, _is_postgres_url
from ygo_app.database import Base
from ygo_app.migration_bootstrap import stamp_legacy_schema_if_needed
from ygo_app import models  # noqa: F401

config = context.config
migration_url = database_url_for_migrations()
config.set_main_option("sqlalchemy.url", migration_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        migration_url,
        poolclass=pool.NullPool,
        connect_args=postgres_connect_args(migration_url),
    )
    use_transactional_ddl = not _is_postgres_url(migration_url)
    with connectable.connect() as connection:
        stamped = stamp_legacy_schema_if_needed(connection, config)
        if stamped:
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            transactional_ddl=use_transactional_ddl,
        )
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
