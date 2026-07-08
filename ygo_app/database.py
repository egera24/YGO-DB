from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from ygo_app.config import DATABASE_URL

_connect_args: dict = {}
_engine_url = DATABASE_URL

_engine_kwargs: dict = {}

if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
elif DATABASE_URL.startswith("postgresql"):
    url = make_url(DATABASE_URL)
    query = dict(url.query)
    if "sslmode" not in query:
        # Neon and most cloud Postgres require TLS
        _connect_args["sslmode"] = "require"
    # Batch executemany INSERT/UPDATE/DELETE into few round-trips. Critical for
    # bulk collection imports against high-latency cloud Postgres (Neon), where
    # per-row statements would otherwise cost one network hop each.
    _engine_kwargs["executemany_mode"] = "values_plus_batch"
    _engine_kwargs["executemany_batch_page_size"] = 1000

engine = create_engine(
    _engine_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
    pool_recycle=300,
    **_engine_kwargs,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record):
    if engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def is_sqlite() -> bool:
    return engine.dialect.name == "sqlite"


def is_postgres() -> bool:
    return engine.dialect.name == "postgresql"
