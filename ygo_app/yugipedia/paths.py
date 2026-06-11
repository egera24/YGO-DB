"""Default paths for Yugipedia catalog scrape outputs."""

from pathlib import Path

from ygo_app.config import DATA_DIR
from ygo_app.image_mirror import IMAGES_MANIFEST_PATH  # noqa: F401 (re-export)

CATALOG_DIR = DATA_DIR / "catalog"
PASSCODE_LIST_PATH = CATALOG_DIR / "yugipedia_passcode_list.json"
ALL_CARDS_PATH = CATALOG_DIR / "yugipedia_all_cards.json"
REJECTED_PATH = CATALOG_DIR / "yugipedia_rejected_cards.json"


def ensure_catalog_dir() -> Path:
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    return CATALOG_DIR
