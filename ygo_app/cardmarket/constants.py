"""Cardmarket scrape configuration."""

from typing import Literal

FetchBackend = Literal["cloudscraper", "playwright"]

BASE_URL = "https://www.cardmarket.com"
SEARCH_URL = (
    f"{BASE_URL}/en/YuGiOh/Products/Search?"
    "searchMode=v1&idCategory=0&idExpansion=0&onlyAvailable=on&idRarity=0&perSite=1"
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Price sync (detail pages)
DEFAULT_WORKERS = 8
DEFAULT_REQUESTS_PER_SECOND = 4.0
MAX_RETRIES = 3
RETRY_DELAY_RANGE = (3, 5)
REQUEST_TIMEOUT = 20

# Discovery (expansion list pages)
DISCOVERY_REQUESTS_PER_SECOND = 3.0
DISCOVERY_MAX_RETRIES = 5

# Browser (Playwright) mode — conservative rates
BROWSER_DEFAULT_WORKERS = 1
BROWSER_DISCOVERY_REQUESTS_PER_SECOND = 0.75
BROWSER_DEFAULT_REQUESTS_PER_SECOND = 1.0

# 429 / rate-limit handling
RATE_LIMIT_429_BASE_SECONDS = 60
CIRCUIT_BREAKER_429_THRESHOLD = 5
CIRCUIT_BREAKER_429_COOLDOWN_SECONDS = 900

# Incremental TTL
DEFAULT_MAX_AGE_DAYS = 7
EXPANSION_CACHE_MAX_AGE_DAYS = 30

CHECKPOINT_EVERY = 100
SESSION_REUSE_COUNT = 10
RANDOM_JITTER = 0.2

DISCOVERY_MATCHED = "matched"
DISCOVERY_UNMATCHED = "unmatched"
DISCOVERY_ERROR = "error"
