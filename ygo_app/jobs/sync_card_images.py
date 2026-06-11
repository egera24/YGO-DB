"""Mirror card images from Yugipedia to an S3-compatible bucket (Cloudflare R2).

Reads data/catalog/yugipedia_all_cards.json, downloads each card's full image
once, converts to WebP (full + 150px thumbnail), and uploads with immutable
cache headers. Incremental: passcodes whose objects already exist are skipped
(use --force to re-mirror). Writes data/catalog/images_manifest.json listing
mirrored passcodes, consumed by the catalog import to rewrite image URLs.

Required env vars: S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY,
S3_BUCKET (IMAGE_BASE_URL is used at import time, not here).
"""

from __future__ import annotations

import argparse
import io
import random
import re
import sys
import time
from pathlib import Path

from ygo_app import config
from ygo_app.image_mirror import (
    full_image_key,
    load_images_manifest,
    save_images_manifest,
    small_image_key,
)
from ygo_app.yugipedia.constants import MAX_RETRIES, RETRY_DELAYS
from ygo_app.yugipedia.http_client import RateLimiter, create_scraper
from ygo_app.yugipedia.images import passcode_to_int
from ygo_app.yugipedia.paths import ALL_CARDS_PATH, IMAGES_MANIFEST_PATH

WEBP_QUALITY = 82
SMALL_WIDTH = 150
KEY_PREFIX = "cards/"
CACHE_CONTROL = "public, max-age=31536000, immutable"
PROGRESS_EVERY = 100
# Image CDN is lighter-weight than wiki pages; still be polite.
DOWNLOAD_MIN_INTERVAL = 0.4

_rate_limiter = RateLimiter(DOWNLOAD_MIN_INTERVAL)


def build_s3_client():
    missing = [
        name
        for name, value in (
            ("S3_ENDPOINT_URL", config.S3_ENDPOINT_URL),
            ("S3_ACCESS_KEY_ID", config.S3_ACCESS_KEY_ID),
            ("S3_SECRET_ACCESS_KEY", config.S3_SECRET_ACCESS_KEY),
            ("S3_BUCKET", config.S3_BUCKET),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing env vars for image mirror: {', '.join(missing)}")
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=config.S3_ENDPOINT_URL,
        aws_access_key_id=config.S3_ACCESS_KEY_ID,
        aws_secret_access_key=config.S3_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def list_existing_keys(s3, bucket: str, *, prefix: str = KEY_PREFIX) -> set[str]:
    keys: set[str] = set()
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.add(obj["Key"])
    return keys


_FULL_KEY_RE = re.compile(r"^cards/(\d+)\.webp$")
_SMALL_KEY_RE = re.compile(r"^cards/(\d+)-small\.webp$")


def manifest_from_bucket(s3, bucket: str, manifest_path: Path = IMAGES_MANIFEST_PATH) -> set[int]:
    """Rebuild the manifest purely from a bucket listing (no downloads)."""
    existing = list_existing_keys(s3, bucket)
    fulls: set[int] = set()
    smalls: set[int] = set()
    for key in existing:
        if m := _FULL_KEY_RE.match(key):
            fulls.add(int(m.group(1)))
        elif m := _SMALL_KEY_RE.match(key):
            smalls.add(int(m.group(1)))
    mirrored = fulls & smalls
    save_images_manifest(mirrored, manifest_path)
    print(f"Manifest rebuilt from bucket: {manifest_path} ({len(mirrored)} passcodes)")
    return mirrored


def fetch_image_bytes(scraper, url: str, *, retries: int = MAX_RETRIES) -> bytes | None:
    for attempt in range(retries):
        try:
            _rate_limiter.acquire()
            response = scraper.get(url, timeout=60)
            response.raise_for_status()
            return response.content
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)] + random.uniform(0, 1))
                continue
            print(f"[FAIL] download {url[:80]} ({type(e).__name__}: {str(e)[:80]})")
    return None


def convert_to_webp(data: bytes) -> tuple[bytes, bytes]:
    """Return (full_webp, small_webp) from source image bytes."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "transparency" in img.info or img.mode == "P" else "RGB")
        full_buf = io.BytesIO()
        img.save(full_buf, "WEBP", quality=WEBP_QUALITY, method=6)

        small = img.copy()
        small.thumbnail((SMALL_WIDTH, SMALL_WIDTH * 4))
        small_buf = io.BytesIO()
        small.save(small_buf, "WEBP", quality=WEBP_QUALITY, method=6)
    return full_buf.getvalue(), small_buf.getvalue()


def upload_webp(s3, bucket: str, key: str, data: bytes) -> None:
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType="image/webp",
        CacheControl=CACHE_CONTROL,
    )


def sync_images(
    entries: list[dict],
    s3,
    bucket: str,
    *,
    force: bool = False,
    limit: int | None = None,
    manifest_path: Path = IMAGES_MANIFEST_PATH,
) -> dict[str, int]:
    """Mirror images for entries; returns counters and writes the manifest."""
    scraper = create_scraper()

    print(f"Listing existing objects in bucket '{bucket}' ...")
    existing = list_existing_keys(s3, bucket)
    print(f"Found {len(existing)} existing objects")

    mirrored: set[int] = set()
    counters = {"skipped_existing": 0, "uploaded": 0, "no_image": 0, "failed": 0}
    candidates = []
    for entry in entries:
        pid = passcode_to_int(entry.get("id"))
        if pid is None:
            continue
        candidates.append((pid, entry.get("image_url")))
    if limit is not None:
        candidates = candidates[:limit]

    total = len(candidates)
    print(f"Syncing images for {total} cards (force={force})")

    for index, (pid, source_url) in enumerate(candidates, start=1):
        full_key = full_image_key(pid)
        small_key = small_image_key(pid)
        already = full_key in existing and small_key in existing

        if already and not force:
            mirrored.add(pid)
            counters["skipped_existing"] += 1
        elif not source_url:
            if already:
                # Keep serving the previously mirrored art even if the latest
                # scrape found no image for this card.
                mirrored.add(pid)
            counters["no_image"] += 1
        else:
            data = fetch_image_bytes(scraper, source_url)
            if data is None:
                if already:
                    mirrored.add(pid)
                counters["failed"] += 1
            else:
                try:
                    full_webp, small_webp = convert_to_webp(data)
                except Exception as e:
                    print(f"[FAIL] convert pid={pid} ({type(e).__name__}: {str(e)[:80]})")
                    counters["failed"] += 1
                else:
                    upload_webp(s3, bucket, full_key, full_webp)
                    upload_webp(s3, bucket, small_key, small_webp)
                    mirrored.add(pid)
                    counters["uploaded"] += 1

        if index % PROGRESS_EVERY == 0 or index == total:
            print(
                f"[PROGRESS] {index}/{total} "
                f"uploaded={counters['uploaded']} existing={counters['skipped_existing']} "
                f"no_image={counters['no_image']} failed={counters['failed']}"
            )

    # Preserve previously mirrored passcodes not present in this JSON slice
    # (e.g. test/limit runs) so the manifest never shrinks accidentally.
    previous = load_images_manifest(manifest_path)
    candidate_pids = {pid for pid, _ in candidates}
    mirrored |= previous - candidate_pids

    save_images_manifest(mirrored, manifest_path)
    print(f"Manifest written: {manifest_path} ({len(mirrored)} passcodes)")
    return counters


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mirror card images to S3-compatible storage")
    parser.add_argument("--json", type=Path, default=ALL_CARDS_PATH, help="Path to yugipedia_all_cards.json")
    parser.add_argument("--manifest", type=Path, default=IMAGES_MANIFEST_PATH, help="Manifest output path")
    parser.add_argument("--limit", type=int, default=None, help="Only process first N cards (testing)")
    parser.add_argument("--force", action="store_true", help="Re-download and re-upload existing objects")
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="Rebuild the manifest from the bucket listing without downloading/uploading",
    )
    args = parser.parse_args(argv)

    try:
        s3 = build_s3_client()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    if args.manifest_only:
        manifest_from_bucket(s3, config.S3_BUCKET, args.manifest)
        return 0

    if not args.json.exists():
        print(f"Catalog file not found: {args.json}", file=sys.stderr)
        return 1

    from ygo_app.jobs.import_catalog_yugipedia import load_yugipedia_cards

    entries = load_yugipedia_cards(args.json)
    counters = sync_images(
        entries,
        s3,
        config.S3_BUCKET,
        force=args.force,
        limit=args.limit,
        manifest_path=args.manifest,
    )
    print(
        "Image sync complete: "
        f"uploaded={counters['uploaded']} existing={counters['skipped_existing']} "
        f"no_image={counters['no_image']} failed={counters['failed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
