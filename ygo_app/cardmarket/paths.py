"""Paths for Cardmarket catalog artifacts (gitignored under data/catalog/)."""

import re
from pathlib import Path

from ygo_app import config

CATALOG_DIR = config.DATA_DIR / "catalog"
CARDMARKET_PRICES_PATH = CATALOG_DIR / "cardmarket_prices.json"
CARDMARKET_CACHE_DB = config.DATA_DIR / "catalog" / "cardmarket_cache.db"
R2_CARDMARKET_ARCHIVE_PREFIX = "archives"
PRICES_ARCHIVE_PREFIX = f"{R2_CARDMARKET_ARCHIVE_PREFIX}/cardmarket_prices_"
LEGACY_R2_CARDMARKET_PRICES_KEY = "catalog/cardmarket_prices.json"

_LEGACY_PRICES_ARCHIVE_KEY_RE = re.compile(
    rf"^{re.escape(PRICES_ARCHIVE_PREFIX)}(\d{{8}}_\d{{4}})\.zip$"
)
_NESTED_PRICES_ARCHIVE_KEY_RE = re.compile(
    rf"^{re.escape(R2_CARDMARKET_ARCHIVE_PREFIX)}/"
    r"(\d{4})/(\d{2})/(\d{2})/(\d{4})/cardmarket_prices\.zip$"
)


def archive_run_prefix(run_ts: str) -> str:
    date_part, time_part = run_ts.split("_", 1)
    return (
        f"{R2_CARDMARKET_ARCHIVE_PREFIX}/{date_part[:4]}/"
        f"{date_part[4:6]}/{date_part[6:8]}/{time_part}"
    )


def catalog_archive_key(run_ts: str) -> str:
    return f"{archive_run_prefix(run_ts)}/catalog_archive.zip"


def prices_archive_key(run_ts: str) -> str:
    return f"{archive_run_prefix(run_ts)}/cardmarket_prices.zip"


def legacy_prices_archive_key(run_ts: str) -> str:
    return f"{PRICES_ARCHIVE_PREFIX}{run_ts}.zip"


def run_log_key(run_ts: str) -> str:
    return f"{archive_run_prefix(run_ts)}/sync_price_log.log.br"


def pipeline_report_key(run_ts: str) -> str:
    return f"{archive_run_prefix(run_ts)}/sync_price_report.json.br"


def run_ts_from_prices_archive_key(key: str) -> str | None:
    nested = _NESTED_PRICES_ARCHIVE_KEY_RE.match(key)
    if nested:
        yyyy, mm, dd, hhmm = nested.groups()
        return f"{yyyy}{mm}{dd}_{hhmm}"
    legacy = _LEGACY_PRICES_ARCHIVE_KEY_RE.match(key)
    if legacy:
        return legacy.group(1)
    return None
DEFAULT_CATALOG_PATH = CATALOG_DIR / "yugipedia_all_cards.json"

# Official catalog raw downloads
CARDMARKET_RAW_DIR = CATALOG_DIR / "cardmarket_raw"
CARDMARKET_PRODUCTS_SINGLES_RAW_PATH = CARDMARKET_RAW_DIR / "products_singles.json"
CARDMARKET_PRODUCTS_NONSINGLES_RAW_PATH = CARDMARKET_RAW_DIR / "products_nonsingles.json"
CARDMARKET_PRICE_GUIDE_RAW_PATH = CARDMARKET_RAW_DIR / "price_guide.json"
