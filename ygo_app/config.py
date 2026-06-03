import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")
DATA_DIR = ROOT_DIR / "data"

ENV = os.getenv("ENV", "development").lower()
IS_PRODUCTION = ENV == "production"


def _normalize_database_url(raw: str | None) -> str | None:
    if raw is None:
        return None
    url = raw.strip()
    if not url:
        return None
    if len(url) >= 2 and url[0] == url[-1] and url[0] in "\"'":
        url = url[1:-1].strip()
    if url.upper().startswith("DATABASE_URL="):
        url = url.split("=", 1)[1].strip()
    return url or None


def _debug_log_database_url(raw: str | None, normalized: str | None) -> None:
    # #region agent log
    try:
        stripped = raw.strip() if raw else ""
        payload = {
            "sessionId": "387ea1",
            "hypothesisId": "A-E",
            "location": "config.py:_debug_log_database_url",
            "message": "DATABASE_URL env diagnostics",
            "data": {
                "raw_len": len(raw) if raw else 0,
                "stripped_len": len(stripped),
                "is_whitespace_only": bool(raw and not stripped),
                "has_wrapping_quotes": bool(
                    len(stripped) >= 2
                    and stripped[0] == stripped[-1]
                    and stripped[0] in "\"'"
                ),
                "has_env_prefix": stripped.upper().startswith("DATABASE_URL="),
                "starts_postgresql": stripped.startswith("postgresql"),
                "starts_postgres_scheme": stripped.startswith("postgres:"),
                "normalized_len": len(normalized) if normalized else 0,
                "uses_sqlite_fallback": normalized is None,
            },
            "timestamp": int(time.time() * 1000),
        }
        with open(ROOT_DIR / "debug-387ea1.log", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except OSError:
        pass
    # #endregion


_raw_database_url = os.getenv("DATABASE_URL")
DATABASE_URL = _normalize_database_url(_raw_database_url)
_debug_log_database_url(_raw_database_url, DATABASE_URL)

if not DATABASE_URL:
    DB_PATH = DATA_DIR / "ygo.db"
    DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"
else:
    DB_PATH = None
    try:
        make_url(DATABASE_URL)
    except Exception as exc:
        raise RuntimeError(
            "DATABASE_URL is set but not a valid SQLAlchemy URL. "
            "Use a Neon pooled URL like "
            "postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require "
            f"(length={len(DATABASE_URL)}, error={exc})"
        ) from exc

SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me-in-production")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))
PORT = int(os.getenv("PORT", "8000"))

YGO_API_URL = os.getenv(
    "YGO_API_URL", "https://db.ygoprodeck.com/api/v7/cardinfo.php"
)

SEARCH_DEFAULT_LIMIT = int(
    os.getenv("SEARCH_DEFAULT_LIMIT", "200" if IS_PRODUCTION else "1000")
)
SEARCH_MAX_LIMIT = int(
    os.getenv("SEARCH_MAX_LIMIT", "500" if IS_PRODUCTION else "25000")
)

DEFAULT_CARDS_JSON = ROOT_DIR / "all_cards.json"
DEFAULT_COLLECTION_CSV = ROOT_DIR / "my_collection.csv"

DATA_DIR.mkdir(parents=True, exist_ok=True)
