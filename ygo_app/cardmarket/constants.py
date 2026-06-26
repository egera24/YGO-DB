"""Cardmarket scrape configuration."""

from typing import Literal

FetchBackend = Literal["cloudscraper", "curl_cffi", "playwright"]

BASE_URL = "https://www.cardmarket.com"
SEARCH_URL = (
    f"{BASE_URL}/en/YuGiOh/Products/Search?"
    "searchMode=v1&idCategory=0&idExpansion=0&onlyAvailable=on&idRarity=0&perSite=1&mode=list"
)
# Product-search URL used to verify curl_cffi can scrape (job 2 traffic pattern).
CARD_LIST_PROBE_URL = (
    f"{BASE_URL}/en/YuGiOh/Products/Search?"
    "searchMode=v1&idCategory=0&idExpansion=1&onlyAvailable=on&idRarity=0&site=1&mode=list"
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

USER_AGENTS = [
    USER_AGENT,
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

# Price sync (detail pages)
DEFAULT_WORKERS = 2
DEFAULT_REQUESTS_PER_SECOND = 0.33
MAX_RETRIES = 3
RETRY_DELAY_RANGE = (3, 5)
REQUEST_TIMEOUT = 20

# Discovery (expansion list pages)
DISCOVERY_REQUESTS_PER_SECOND = 0.25
DISCOVERY_MAX_RETRIES = 5

# Browser (Playwright) mode — verified stable rate for card-list scraping
BROWSER_DEFAULT_WORKERS = 1
BROWSER_DISCOVERY_REQUESTS_PER_SECOND = 0.05
BROWSER_DEFAULT_REQUESTS_PER_SECOND = 0.2

# Human-like pacing between browser requests (seconds, inclusive random range).
# Keep reasonably high — randomized 2–8 s gaps matter more than session rotation for CF.
INTER_PAGE_DELAY_BROWSER = (2.0, 8.0)
INTER_PAGE_DELAY_HTTP = (1.5, 3.0)
INTER_EXPANSION_DELAY_BROWSER = (15.0, 30.0)

# 429 / rate-limit handling
RATE_LIMIT_429_BASE_SECONDS = 120
CIRCUIT_BREAKER_429_THRESHOLD = 3
CIRCUIT_BREAKER_429_COOLDOWN_SECONDS = 900
LONG_BAN_RETRY_AFTER_SECONDS = 600
LONG_BAN_ASSUMED_RETRY_AFTER_SECONDS = 3600.0

# Cloudflare rate-limit / Error 1015 HTML markers
CF_RATE_LIMIT_MARKERS = (
    "error 1015",
    "you are being rate limited",
    "banned you temporarily",
)

# Adaptive throttle
ADAPTIVE_THROTTLE_SLOW_FACTOR = 2.0
ADAPTIVE_THROTTLE_RECOVER_FACTOR = 0.9
ADAPTIVE_THROTTLE_MIN_RPS = 1.0 / 30.0
ADAPTIVE_THROTTLE_SUCCESS_STREAK = 50

# Cloudflare challenge backoff (seconds)
CF_CHALLENGE_RETRY_DELAYS = (5, 10, 20)

# Incremental TTL
DEFAULT_MAX_AGE_DAYS = 7
EXPANSION_CACHE_MAX_AGE_DAYS = 30

CHECKPOINT_EVERY = 100
SESSION_REUSE_COUNT = 10
RANDOM_JITTER = 1.0

DISCOVERY_MATCHED = "matched"
DISCOVERY_UNMATCHED = "unmatched"
DISCOVERY_ERROR = "error"

CURL_CFFI_IMPERSONATE = "chrome120"

# Phase 2 recovery (serial) when expansions/cards fail phase 1
RECOVERY_REQUESTS_PER_SECOND = 0.15
