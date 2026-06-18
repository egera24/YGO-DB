import os
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


DATABASE_URL = _normalize_database_url(os.getenv("DATABASE_URL"))
DATABASE_URL_MIGRATIONS = _normalize_database_url(os.getenv("DATABASE_URL_MIGRATIONS"))


def _is_postgres_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        driver = make_url(url).drivername.split("+", 1)[0]
        return driver in ("postgresql", "postgres")
    except Exception:
        return url.startswith(("postgresql", "postgres"))


def postgres_connect_args(url: str) -> dict:
    if not _is_postgres_url(url):
        return {}
    try:
        if "sslmode" in dict(make_url(url).query):
            return {}
    except Exception:
        pass
    return {"sslmode": "require"}


def database_url_for_migrations() -> str:
    """
    URL for Alembic / DDL. Prefer DATABASE_URL_MIGRATIONS; else direct Neon host
    (strip -pooler). Pooled PgBouncer can prevent migrations from persisting.
    """
    if DATABASE_URL_MIGRATIONS:
        return DATABASE_URL_MIGRATIONS
    if not DATABASE_URL or not _is_postgres_url(DATABASE_URL):
        return DATABASE_URL or f"sqlite:///{(DATA_DIR / 'ygo.db').as_posix()}"
    try:
        url = make_url(DATABASE_URL)
        host = url.host or ""
        if host and "-pooler" in host:
            url = url.set(host=host.replace("-pooler", "", 1))
        return url.render_as_string(hide_password=False)
    except Exception:
        return DATABASE_URL


def database_host_fingerprint(url: str | None) -> str | None:
    """Host label for logs (no credentials)."""
    if not url:
        return None
    try:
        host = make_url(url).host or ""
        if "-pooler" in host:
            return "neon-pooler"
        if host.endswith(".neon.tech"):
            return "neon-direct"
        if host in ("localhost", "127.0.0.1"):
            return "local"
        return "other"
    except Exception:
        return "invalid"


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

EMAIL_BACKEND = (os.getenv("EMAIL_BACKEND") or "console").strip().lower()
BREVO_API_KEY = (os.getenv("BREVO_API_KEY") or "").strip() or None
EMAIL_FROM = (os.getenv("EMAIL_FROM") or "").strip() or None
EMAIL_OTP_TTL_MINUTES = int(os.getenv("EMAIL_OTP_TTL_MINUTES", "10"))
EMAIL_OTP_MAX_ATTEMPTS = int(os.getenv("EMAIL_OTP_MAX_ATTEMPTS", "5"))
TURNSTILE_SITE_KEY = (os.getenv("TURNSTILE_SITE_KEY") or "").strip() or None
TURNSTILE_SECRET_KEY = (os.getenv("TURNSTILE_SECRET_KEY") or "").strip() or None

YGO_API_URL = os.getenv(
    "YGO_API_URL", "https://db.ygoprodeck.com/api/v7/cardinfo.php"
)

# S3-compatible card image mirror (Cloudflare R2; portable to B2/AWS/MinIO).
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL") or None
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID") or None
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY") or None
S3_BUCKET = os.getenv("S3_BUCKET") or None
# Public base URL images are served from (r2.dev subdomain or custom domain).
IMAGE_BASE_URL = (os.getenv("IMAGE_BASE_URL") or "").strip().rstrip("/") or None

SEARCH_DEFAULT_LIMIT = int(
    os.getenv("SEARCH_DEFAULT_LIMIT", "200" if IS_PRODUCTION else "1000")
)
SEARCH_MAX_LIMIT = int(
    os.getenv("SEARCH_MAX_LIMIT", "500" if IS_PRODUCTION else "25000")
)

DEFAULT_CARDS_JSON = ROOT_DIR / "all_cards.json"
DEFAULT_COLLECTION_CSV = ROOT_DIR / "my_collection.csv"

# Optional residential proxy for local Cardmarket scrape (http://user:pass@host:port).
CARDMARKET_HTTP_PROXY = (os.getenv("CARDMARKET_HTTP_PROXY") or "").strip() or None

DATA_DIR.mkdir(parents=True, exist_ok=True)
