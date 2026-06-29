import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")
DATA_DIR = ROOT_DIR / "data"

ENV = os.getenv("ENV", "development").lower()
IS_PRODUCTION = ENV == "production"

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    DB_PATH = DATA_DIR / "ygo.db"
    DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"
else:
    DB_PATH = None

SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me-in-production")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))
PORT = int(os.getenv("PORT", "8000"))

YGO_API_URL = os.getenv(
    "YGO_API_URL", "https://db.ygoprodeck.com/api/v7/cardinfo.php"
)

# S3-compatible storage (Cloudflare R2; card images + Cardmarket catalog).
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL") or None
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID") or None
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY") or None
S3_BUCKET = os.getenv("S3_BUCKET") or None
S3_CARDMARKET_BUCKET = os.getenv("S3_CARDMARKET_BUCKET") or None

SEARCH_DEFAULT_LIMIT = int(
    os.getenv("SEARCH_DEFAULT_LIMIT", "200" if IS_PRODUCTION else "1000")
)
SEARCH_MAX_LIMIT = int(
    os.getenv("SEARCH_MAX_LIMIT", "500" if IS_PRODUCTION else "25000")
)

DEFAULT_CARDS_JSON = ROOT_DIR / "all_cards.json"
DEFAULT_COLLECTION_CSV = ROOT_DIR / "my_collection.csv"

DATA_DIR.mkdir(parents=True, exist_ok=True)
