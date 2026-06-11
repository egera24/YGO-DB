"""Vendor-neutral helpers for card images mirrored to S3-compatible storage.

Object keys are passcode-based so the bucket can be migrated to any other
S3-compatible vendor (rclone sync + change IMAGE_BASE_URL) with no code change:

    cards/{passcode}.webp        full image
    cards/{passcode}-small.webp  ~150px thumbnail

The sync job (ygo_app.jobs.sync_card_images) writes a manifest JSON listing
mirrored passcodes; the catalog import rewrites image URLs for those passcodes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ygo_app import config

# Defined here (not yugipedia.paths) to avoid a circular import via the
# yugipedia package __init__; paths.py re-exports it.
IMAGES_MANIFEST_PATH = config.DATA_DIR / "catalog" / "images_manifest.json"

FULL_IMAGE_KEY_TEMPLATE = "cards/{pid}.webp"
SMALL_IMAGE_KEY_TEMPLATE = "cards/{pid}-small.webp"


def full_image_key(pid: int) -> str:
    return FULL_IMAGE_KEY_TEMPLATE.format(pid=pid)


def small_image_key(pid: int) -> str:
    return SMALL_IMAGE_KEY_TEMPLATE.format(pid=pid)


def mirrored_image_urls(pid: int, base_url: str) -> dict[str, str]:
    base = base_url.rstrip("/")
    return {
        "image_url": f"{base}/{full_image_key(pid)}",
        "image_url_small": f"{base}/{small_image_key(pid)}",
    }


def load_images_manifest(path: Path = IMAGES_MANIFEST_PATH) -> set[int]:
    """Passcodes mirrored to the bucket; empty set when no/invalid manifest."""
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    passcodes = data.get("passcodes") if isinstance(data, dict) else data
    if not isinstance(passcodes, list):
        return set()
    out: set[int] = set()
    for p in passcodes:
        try:
            out.add(int(p))
        except (TypeError, ValueError):
            continue
    return out


def save_images_manifest(passcodes: set[int], path: Path = IMAGES_MANIFEST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(passcodes),
        "passcodes": sorted(passcodes),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


_manifest_cache: set[int] | None = None


def _cached_manifest() -> set[int]:
    global _manifest_cache
    if _manifest_cache is None:
        _manifest_cache = load_images_manifest()
    return _manifest_cache


def clear_manifest_cache() -> None:
    global _manifest_cache
    _manifest_cache = None


def rewrite_image_urls(
    pid: int,
    image_url: str | None,
    image_url_small: str | None,
    *,
    base_url: str | None = None,
    manifest: set[int] | None = None,
) -> tuple[str | None, str | None]:
    """Return mirrored URLs when IMAGE_BASE_URL is set and the passcode is mirrored.

    Falls back to the original (Yugipedia) URLs otherwise, so a missing or
    partial mirror never breaks the catalog import.
    """
    base = base_url if base_url is not None else config.IMAGE_BASE_URL
    if not base:
        return image_url, image_url_small
    mirrored = manifest if manifest is not None else _cached_manifest()
    if pid not in mirrored:
        return image_url, image_url_small
    urls = mirrored_image_urls(pid, base)
    return urls["image_url"], urls["image_url_small"]
