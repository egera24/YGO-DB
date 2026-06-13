"""Paths for Cardmarket scrape artifacts (gitignored under data/catalog/)."""

from pathlib import Path

CATALOG_DIR = Path("data/catalog")
CHECKPOINT_PATH = CATALOG_DIR / "cardmarket_prices_checkpoint.json"
FAILURES_PATH = CATALOG_DIR / "cardmarket_prices_failures.json"
