"""Paths for Cardmarket catalog artifacts (gitignored under data/catalog/)."""

from pathlib import Path

from ygo_app import config

CATALOG_DIR = config.DATA_DIR / "catalog"
CARDMARKET_PRICES_PATH = CATALOG_DIR / "cardmarket_prices.json"
CARDMARKET_CACHE_DB = config.DATA_DIR / "catalog" / "cardmarket_cache.db"
R2_CARDMARKET_ARCHIVE_PREFIX = "archives"
PRICES_ARCHIVE_PREFIX = f"{R2_CARDMARKET_ARCHIVE_PREFIX}/cardmarket_prices_"
LEGACY_R2_CARDMARKET_PRICES_KEY = "catalog/cardmarket_prices.json"


def prices_archive_key(run_ts: str) -> str:
    return f"{PRICES_ARCHIVE_PREFIX}{run_ts}.zip"
DEFAULT_CATALOG_PATH = CATALOG_DIR / "yugipedia_all_cards.json"

# Official catalog raw downloads
CARDMARKET_RAW_DIR = CATALOG_DIR / "cardmarket_raw"
CARDMARKET_PRODUCTS_SINGLES_RAW_PATH = CARDMARKET_RAW_DIR / "products_singles.json"
CARDMARKET_PRODUCTS_NONSINGLES_RAW_PATH = CARDMARKET_RAW_DIR / "products_nonsingles.json"
CARDMARKET_PRICE_GUIDE_RAW_PATH = CARDMARKET_RAW_DIR / "price_guide.json"
