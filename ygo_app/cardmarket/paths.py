"""Paths for Cardmarket scrape artifacts (gitignored under data/catalog/)."""

from pathlib import Path

from ygo_app import config

CATALOG_DIR = config.DATA_DIR / "catalog"
CARDMARKET_PRICES_PATH = CATALOG_DIR / "cardmarket_prices.json"
CARDMARKET_CACHE_DB = config.DATA_DIR / "catalog" / "cardmarket_cache.db"
CARDMARKET_BROWSER_STATE_PATH = CATALOG_DIR / "cardmarket_browser_state.json"
R2_CARDMARKET_PRICES_KEY = "catalog/cardmarket_prices.json"
CHECKPOINT_PATH = CATALOG_DIR / "cardmarket_prices_checkpoint.json"
FAILURES_PATH = CATALOG_DIR / "cardmarket_prices_failures.json"
DEFAULT_CATALOG_PATH = CATALOG_DIR / "yugipedia_all_cards.json"

# 3-step scrape pipeline artifacts
CARDMARKET_EXPANSION_LIST_PATH = CATALOG_DIR / "cardmarket_expansion_list.json"
CARDMARKET_CARD_LIST_PATH = CATALOG_DIR / "cardmarket_card_list.json"
CARDMARKET_EMPTY_EXPANSIONS_PATH = CATALOG_DIR / "cardmarket_empty_expansions.json"
CARDMARKET_REJECTED_EXPANSIONS_PATH = CATALOG_DIR / "cardmarket_rejected_expansions.json"
CARDMARKET_CARD_DETAILS_PATH = CATALOG_DIR / "cardmarket_card_details.json"
CARDMARKET_CARD_DETAILS_REJECTION_PATH = CATALOG_DIR / "cardmarket_card_details_rejection.json"

CARDMARKET_EXPANSION_LIST_CHECKPOINT_PATH = CATALOG_DIR / "cardmarket_expansion_list_checkpoint.json"
CARDMARKET_CARD_LIST_CHECKPOINT_PATH = CATALOG_DIR / "cardmarket_card_list_checkpoint.json"
CARDMARKET_CARD_LIST_RECOVERY_CHECKPOINT_PATH = CATALOG_DIR / "cardmarket_card_list_recovery_checkpoint.json"
CARDMARKET_CARD_DETAILS_CHECKPOINT_PATH = CATALOG_DIR / "cardmarket_card_details_checkpoint.json"

CARDMARKET_INCREMENTAL_CONFLICTS_PATH = CATALOG_DIR / "cardmarket_incremental_conflicts.json"
CARDMARKET_INCREMENTAL_REPORT_PATH = CATALOG_DIR / "cardmarket_incremental_report.json"
