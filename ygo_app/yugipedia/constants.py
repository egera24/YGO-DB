"""Shared constants for Yugipedia scrapers (Wikimedia User-Agent policy)."""

USER_AGENT = (
    "YugipediaCardBot/1.0 (https://github.com/egera24; egera24@gmail.com) "
    "requests/2.31.0"
)

MAX_WORKERS = 8
REQUESTS_PER_SECOND = 3
MIN_REQUEST_INTERVAL = 1.0 / REQUESTS_PER_SECOND

MAX_RETRIES = 5
REQUEST_TIMEOUT = 60
RETRY_DELAYS = [3, 5, 10, 15, 20]

CHECKPOINT_EVERY = 200

# Details scrape: observability and safety (GHA batch jobs).
HEARTBEAT_INTERVAL_SECONDS = 60
STALL_WARN_SECONDS = 120
STALL_ABORT_SECONDS = 600
DEGRADED_RATE_THRESHOLD = 1.0
PROGRESS_LOG_EVERY = 50
FAILED_RETRY_ROUNDS = 2
# Per in-flight card: HTTP retries + delays; pool wait uses this ceiling.
PER_CARD_POOL_TIMEOUT_SECONDS = 240
SLOW_REQUEST_WARN_SECONDS = 45
# Errata/tips probe: missing pages may 404 or hang; avoid long retry loops.
SUPPLEMENT_PROBE_TIMEOUT = 25
SUPPLEMENT_PROBE_RETRIES = 1

# Short codes for known rarities; unknown → empty (import uses full rarity label).
RARITY_CODES: dict[str, str] = {
    "Common": "C",
    "Rare": "R",
    "Super Rare": "SR",
    "Ultra Rare": "UR",
    "Secret Rare": "ScR",
    "Ultimate Rare": "UtR",
    "Ghost Rare": "GR",
    "Holographic Rare": "HR",
    "Gold Rare": "GUR",
    "Collector's Rare": "CR",
    "Starlight Rare": "StR",
    "Prismatic Secret Rare": "PSR",
    "Platinum Rare": "PlR",
    "Platinum Secret Rare": "PScR",
    "Quarter Century Secret Rare": "QCR",
    "Parallel Rare": "PR",
    "Starfoil Rare": "SFR",
    "Mosaic Rare": "MR",
    "Duel Terminal Rare": "DTR",
    "10000 Secret Rare": "10000ScR",
}

MONSTER_TYPES = [
    "Aqua",
    "Beast",
    "Beast-Warrior",
    "Cyberse",
    "Dinosaur",
    "Divine-Beast",
    "Dragon",
    "Fairy",
    "Fiend",
    "Fish",
    "Insect",
    "Machine",
    "Plant",
    "Psychic",
    "Pyro",
    "Reptile",
    "Rock",
    "Sea Serpent",
    "Spellcaster",
    "Thunder",
    "Warrior",
    "Winged Beast",
    "Wyrm",
    "Zombie",
    "Illusion",
]

MONSTER_MECHANICS = [
    "Normal",
    "Ritual",
    "Fusion",
    "Synchro",
    "Xyz",
    "Pendulum",
    "Link",
    "Flip",
    "Union",
    "Gemini",
    "Toon",
    "Spirit",
]

LINK_MARKER_MAP = {
    "Top-Left": "Top-Left",
    "Top-Center": "Top",
    "Top-Right": "Top-Right",
    "Middle-Left": "Left",
    "Middle-Right": "Right",
    "Bottom-Left": "Bottom-Left",
    "Bottom-Center": "Bottom",
    "Bottom-Right": "Bottom-Right",
}

PASSWORD_RANGES = [
    (0, 9_999_999),
    (10_000_000, 19_999_999),
    (20_000_000, 29_999_999),
    (30_000_000, 39_999_999),
    (40_000_000, 49_999_999),
    (50_000_000, 59_999_999),
    (60_000_000, 69_999_999),
    (70_000_000, 79_999_999),
    (80_000_000, 89_999_999),
    (90_000_000, 99_999_999),
]
