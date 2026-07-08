"""Vendor-neutral helpers for card images mirrored to S3-compatible storage.

Object keys are derived from a stable "stem" so the bucket can be migrated to
any other S3-compatible vendor (rclone sync + change IMAGE_BASE_URL) with no
code change:

    cards/{passcode}.webp        full image (cards with a passcode)
    cards/{passcode}-small.webp  ~300px thumbnail
    cards/pw-{hash}.webp         cards printed without a passcode (keyed by URL)
    cards/pw-{hash}-small.webp

The sync job (ygo_app.jobs.sync_card_images) writes a manifest JSON listing the
mirrored passcodes and passwordless stems; the catalog import rewrites image
URLs for those entries.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ygo_app import config

# Defined here (not yugipedia.paths) to avoid a circular import via the
# yugipedia package __init__; paths.py re-exports it.
IMAGES_MANIFEST_PATH = config.DATA_DIR / "catalog" / "images_manifest.json"

FULL_IMAGE_KEY_TEMPLATE = "cards/{stem}.webp"
SMALL_IMAGE_KEY_TEMPLATE = "cards/{stem}-small.webp"

PASSWORDLESS_STEM_PREFIX = "pw-"


def passwordless_image_stem(source_url: str) -> str:
    """Deterministic object-key stem for a card printed without a passcode."""
    digest = hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:16]
    return f"{PASSWORDLESS_STEM_PREFIX}{digest}"


def image_stem(passcode: int | None, source_url: str | None) -> str | None:
    """Object-key stem for a card: passcode when present, else a URL-based stem."""
    if passcode is not None:
        return str(passcode)
    if source_url:
        return passwordless_image_stem(source_url)
    return None


def full_image_key(stem: int | str) -> str:
    return FULL_IMAGE_KEY_TEMPLATE.format(stem=stem)


def small_image_key(stem: int | str) -> str:
    return SMALL_IMAGE_KEY_TEMPLATE.format(stem=stem)


def mirrored_image_urls(stem: int | str, base_url: str) -> dict[str, str]:
    base = base_url.rstrip("/")
    return {
        "image_url": f"{base}/{full_image_key(stem)}",
        "image_url_small": f"{base}/{small_image_key(stem)}",
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


def load_passwordless_manifest(path: Path = IMAGES_MANIFEST_PATH) -> set[str]:
    """Passwordless stems (pw-<hash>) mirrored to the bucket; empty when absent."""
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(data, dict):
        return set()
    stems = data.get("passwordless")
    if not isinstance(stems, list):
        return set()
    return {str(s) for s in stems if isinstance(s, str)}


def save_images_manifest(
    passcodes: set[int],
    passwordless: set[str] = frozenset(),
    path: Path = IMAGES_MANIFEST_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(passcodes) + len(passwordless),
        "passcodes": sorted(passcodes),
        "passwordless": sorted(passwordless),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


_manifest_cache: set[int] | None = None
_passwordless_manifest_cache: set[str] | None = None


def _cached_manifest() -> set[int]:
    global _manifest_cache
    if _manifest_cache is None:
        _manifest_cache = load_images_manifest()
    return _manifest_cache


def _cached_passwordless_manifest() -> set[str]:
    global _passwordless_manifest_cache
    if _passwordless_manifest_cache is None:
        _passwordless_manifest_cache = load_passwordless_manifest()
    return _passwordless_manifest_cache


def clear_manifest_cache() -> None:
    global _manifest_cache, _passwordless_manifest_cache
    _manifest_cache = None
    _passwordless_manifest_cache = None


def rewrite_image_urls(
    passcode: int | None,
    image_url: str | None,
    image_url_small: str | None,
    *,
    source_url: str | None = None,
    base_url: str | None = None,
    manifest: set[int] | None = None,
    passwordless_manifest: set[str] | None = None,
) -> tuple[str | None, str | None]:
    """Return mirrored URLs when IMAGE_BASE_URL is set and the card is mirrored.

    Real cards match by passcode; cards printed without a passcode match by a
    stem derived from ``source_url``. Falls back to the original (Yugipedia) URLs
    otherwise, so a missing or partial mirror never breaks the catalog import.
    """
    base = base_url if base_url is not None else config.IMAGE_BASE_URL
    if not base:
        return image_url, image_url_small

    if passcode is not None:
        mirrored = manifest if manifest is not None else _cached_manifest()
        if passcode not in mirrored:
            return image_url, image_url_small
        stem: int | str = passcode
    elif source_url:
        stems = (
            passwordless_manifest
            if passwordless_manifest is not None
            else _cached_passwordless_manifest()
        )
        pw_stem = passwordless_image_stem(source_url)
        if pw_stem not in stems:
            return image_url, image_url_small
        stem = pw_stem
    else:
        return image_url, image_url_small

    urls = mirrored_image_urls(stem, base)
    return urls["image_url"], urls["image_url_small"]
