"""Paths for Cardmarket scrape artifacts (gitignored under data/catalog/)."""

from pathlib import Path

from ygo_app import config

CATALOG_DIR = config.DATA_DIR / "catalog"
CARDMARKET_PRICES_PATH = CATALOG_DIR / "cardmarket_prices.json"
CARDMARKET_CACHE_DB = config.DATA_DIR / "catalog" / "cardmarket_cache.db"
R2_CARDMARKET_PRICES_KEY = "catalog/cardmarket_prices.json"
CHECKPOINT_PATH = CATALOG_DIR / "cardmarket_prices_checkpoint.json"
FAILURES_PATH = CATALOG_DIR / "cardmarket_prices_failures.json"
DEFAULT_CATALOG_PATH = CATALOG_DIR / "yugipedia_all_cards.json"
