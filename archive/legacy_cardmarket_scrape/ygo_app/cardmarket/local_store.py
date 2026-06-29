"""Local SQLite cache for export-only Cardmarket scrapes (no Neon)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ygo_app.cardmarket.paths import CARDMARKET_CACHE_DB
from ygo_app.models import Base


def _sqlite_engine(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{path.as_posix()}"
    eng = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return eng


_engines: dict[str, object] = {}
_sessionmakers: dict[str, sessionmaker] = {}


def get_local_session(cache_path: Path = CARDMARKET_CACHE_DB) -> Session:
    key = str(cache_path.resolve())
    if key not in _sessionmakers:
        engine = _sqlite_engine(cache_path)
        Base.metadata.create_all(bind=engine)
        _engines[key] = engine
        _sessionmakers[key] = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return _sessionmakers[key]()


def clear_local_cache(session: Session) -> None:
    from ygo_app.models import CardmarketExpansion, PrintingMarketPrice

    session.query(PrintingMarketPrice).delete()
    session.query(CardmarketExpansion).delete()
    session.commit()
