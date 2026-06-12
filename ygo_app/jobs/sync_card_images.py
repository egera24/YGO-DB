"""Mirror card images from Yugipedia to an S3-compatible bucket (Cloudflare R2).

Reads data/catalog/yugipedia_all_cards.json, downloads each card's full image
once, converts to WebP (full + 300px thumbnail), and uploads with immutable
cache headers. Incremental: passcodes whose objects already exist are skipped
(use --force to re-mirror). Writes data/catalog/images_manifest.json listing
mirrored passcodes, consumed by the catalog import to rewrite image URLs.

Required env vars: S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY,
S3_BUCKET (IMAGE_BASE_URL is used at import time, not here).
"""

from __future__ import annotations

import argparse
import io
import json
import random
import re
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from ygo_app import config
from ygo_app.image_mirror import (
    full_image_key,
    load_images_manifest,
    save_images_manifest,
    small_image_key,
)
from ygo_app.import_progress import ProgressThrottle, eta_seconds
from ygo_app.yugipedia.constants import MAX_RETRIES, MIN_REQUEST_INTERVAL, RETRY_DELAYS
from ygo_app.yugipedia.http_client import RateLimiter, create_scraper
from ygo_app.yugipedia.images import passcode_to_int
from ygo_app.yugipedia.paths import ALL_CARDS_PATH, IMAGES_MANIFEST_PATH
from ygo_app.yugipedia.scrape_progress import log_line

WEBP_QUALITY = 85
WEBP_QUALITY_SMALL = 88
WEBP_METHOD = 4
SMALL_WIDTH = 300
KEY_PREFIX = "cards/"
CACHE_CONTROL = "public, max-age=31536000, immutable"
PROGRESS_EVERY_ROWS = 50
PROGRESS_EVERY_SECONDS = 60.0
FAILURES_FILENAME = "images_sync_failures.json"
DEFAULT_WORKERS = 6

_rate_limiter = RateLimiter(MIN_REQUEST_INTERVAL)
_thread_local = threading.local()


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


def _get_thread_s3():
    """Return a per-thread boto3 client (one per worker thread)."""
    client = getattr(_thread_local, "s3", None)
    if client is None:
        client = build_s3_client()
        _thread_local.s3 = client
    return client


def list_existing_keys(s3, bucket: str, *, prefix: str = KEY_PREFIX) -> set[str]:
    keys: set[str] = set()
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.add(obj["Key"])
        if keys:
            log_line(f"[LIST] listed {len(keys)} objects so far...")
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
    log_line(f"Manifest rebuilt from bucket: {manifest_path} ({len(mirrored)} passcodes)")
    return mirrored


def fetch_image_bytes(
    scraper, url: str, *, retries: int = MAX_RETRIES
) -> tuple[bytes | None, str | None]:
    last_error: str | None = None
    for attempt in range(retries):
        try:
            _rate_limiter.acquire()
            response = scraper.get(url, timeout=60)
            response.raise_for_status()
            return response.content, None
        except Exception as e:
            last_error = f"{type(e).__name__}: {str(e)[:120]}"
            if attempt < retries - 1:
                time.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)] + random.uniform(0, 1))
                continue
    if last_error:
        log_line(f"[FAIL] download {url[:80]} ({last_error})")
    return None, last_error


def convert_to_webp(data: bytes) -> tuple[bytes, bytes]:
    """Return (full_webp, small_webp) from source image bytes."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "transparency" in img.info or img.mode == "P" else "RGB")
        full_buf = io.BytesIO()
        img.save(full_buf, "WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD)

        small = img.copy()
        small.thumbnail((SMALL_WIDTH, SMALL_WIDTH * 4), Image.Resampling.LANCZOS)
        small_buf = io.BytesIO()
        small.save(small_buf, "WEBP", quality=WEBP_QUALITY_SMALL, method=WEBP_METHOD)
    return full_buf.getvalue(), small_buf.getvalue()


def upload_webp(s3, bucket: str, key: str, data: bytes) -> None:
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType="image/webp",
        CacheControl=CACHE_CONTROL,
    )


def _upload_pair(s3, bucket: str, full_key: str, full_webp: bytes, small_key: str, small_webp: bytes) -> None:
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(upload_webp, s3, bucket, full_key, full_webp),
            executor.submit(upload_webp, s3, bucket, small_key, small_webp),
        ]
        for fut in futures:
            fut.result()


@dataclass
class MirrorResult:
    pid: int
    status: str  # skipped_existing | no_image | uploaded | failed
    mirrored: bool = False
    failure: dict | None = None


def _mirror_one_card(
    pid: int,
    source_url: str | None,
    *,
    scraper,
    s3,
    bucket: str,
    existing: set[str],
    force: bool,
    thread_local_s3: bool = False,
) -> MirrorResult:
    full_key = full_image_key(pid)
    small_key = small_image_key(pid)
    already = full_key in existing and small_key in existing

    if already and not force:
        return MirrorResult(pid=pid, status="skipped_existing", mirrored=True)

    if not source_url:
        return MirrorResult(pid=pid, status="no_image", mirrored=already)

    data, download_error = fetch_image_bytes(scraper, source_url)
    if data is None:
        return MirrorResult(
            pid=pid,
            status="failed",
            mirrored=already,
            failure={
                "passcode": pid,
                "stage": "download",
                "reason": download_error or "download failed",
                "url": source_url[:200],
            },
        )

    try:
        full_webp, small_webp = convert_to_webp(data)
    except Exception as e:
        reason = f"{type(e).__name__}: {str(e)[:120]}"
        log_line(f"[FAIL] convert pid={pid} ({reason})")
        return MirrorResult(
            pid=pid,
            status="failed",
            mirrored=already,
            failure={"passcode": pid, "stage": "convert", "reason": reason},
        )

    upload_s3 = _get_thread_s3() if thread_local_s3 else s3
    _upload_pair(upload_s3, bucket, full_key, full_webp, small_key, small_webp)
    return MirrorResult(pid=pid, status="uploaded", mirrored=True)


def _apply_result(
    result: MirrorResult,
    *,
    mirrored: set[int],
    counters: dict[str, int],
    failed_items: list[dict],
) -> None:
    if result.mirrored:
        mirrored.add(result.pid)
    if result.status == "skipped_existing":
        counters["skipped_existing"] += 1
    elif result.status == "no_image":
        counters["no_image"] += 1
    elif result.status == "uploaded":
        counters["uploaded"] += 1
    elif result.status == "failed":
        counters["failed"] += 1
        if result.failure:
            failed_items.append(result.failure)


def _sync_images_parallel(
    candidates: list[tuple[int, str | None]],
    s3,
    bucket: str,
    *,
    existing: set[str],
    force: bool,
    workers: int,
    progress: ProgressThrottle,
    total: int,
    started: float,
    mirrored: set[int],
    counters: dict[str, int],
    failed_items: list[dict],
) -> None:
    scrapers = [create_scraper() for _ in range(workers)]
    lock = threading.Lock()
    completed = 0
    work_index = 0

    def worker_task(worker_id: int, pid: int, source_url: str | None) -> MirrorResult:
        return _mirror_one_card(
            pid,
            source_url,
            scraper=scrapers[worker_id % len(scrapers)],
            s3=s3,
            bucket=bucket,
            existing=existing,
            force=force,
            thread_local_s3=True,
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        in_flight: dict[Future, int] = {}

        def submit_next() -> None:
            nonlocal work_index
            while work_index < total and len(in_flight) < workers:
                pid, source_url = candidates[work_index]
                fut = executor.submit(worker_task, work_index, pid, source_url)
                in_flight[fut] = work_index
                work_index += 1

        submit_next()
        while in_flight:
            done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for fut in done:
                in_flight.pop(fut)
                result = fut.result()
                with lock:
                    _apply_result(
                        result,
                        mirrored=mirrored,
                        counters=counters,
                        failed_items=failed_items,
                    )
                    completed += 1
                    index = completed
                    if progress.should_emit(index) or index == total:
                        eta = eta_seconds(index, total, started)
                        eta_suffix = f" eta={eta:.0f}s" if eta is not None else ""
                        log_line(
                            f"[PROGRESS] {index}/{total} "
                            f"uploaded={counters['uploaded']} existing={counters['skipped_existing']} "
                            f"no_image={counters['no_image']} failed={counters['failed']}{eta_suffix}"
                        )
            submit_next()


def _write_failures(failed_items: list[dict], manifest_path: Path) -> Path | None:
    if not failed_items:
        return None
    failures_path = manifest_path.parent / FAILURES_FILENAME
    failures_path.write_text(json.dumps(failed_items, indent=2), encoding="utf-8")
    log_line(f"Failures written: {failures_path} ({len(failed_items)} items)")
    return failures_path


def sync_images(
    entries: list[dict],
    s3,
    bucket: str,
    *,
    force: bool = False,
    limit: int | None = None,
    manifest_path: Path = IMAGES_MANIFEST_PATH,
    workers: int = DEFAULT_WORKERS,
) -> dict[str, int]:
    """Mirror images for entries; returns counters and writes the manifest."""
    log_line(f"Listing existing objects in bucket '{bucket}' ...")
    existing = list_existing_keys(s3, bucket)
    log_line(f"Found {len(existing)} existing objects")

    mirrored: set[int] = set()
    counters = {"skipped_existing": 0, "uploaded": 0, "no_image": 0, "failed": 0}
    failed_items: list[dict] = []
    candidates = []
    for entry in entries:
        pid = passcode_to_int(entry.get("id"))
        if pid is None:
            continue
        candidates.append((pid, entry.get("image_url")))
    if limit is not None:
        candidates = candidates[:limit]

    total = len(candidates)
    worker_count = max(1, workers)
    log_line(f"[START] bucket={bucket} total={total} force={force} workers={worker_count}")
    progress = ProgressThrottle(every_rows=PROGRESS_EVERY_ROWS, every_seconds=PROGRESS_EVERY_SECONDS)
    started = time.monotonic()

    if worker_count == 1:
        scraper = create_scraper()
        for index, (pid, source_url) in enumerate(candidates, start=1):
            result = _mirror_one_card(
                pid,
                source_url,
                scraper=scraper,
                s3=s3,
                bucket=bucket,
                existing=existing,
                force=force,
            )
            _apply_result(result, mirrored=mirrored, counters=counters, failed_items=failed_items)

            if progress.should_emit(index) or index == total:
                eta = eta_seconds(index, total, started)
                eta_suffix = f" eta={eta:.0f}s" if eta is not None else ""
                log_line(
                    f"[PROGRESS] {index}/{total} "
                    f"uploaded={counters['uploaded']} existing={counters['skipped_existing']} "
                    f"no_image={counters['no_image']} failed={counters['failed']}{eta_suffix}"
                )
    else:
        _sync_images_parallel(
            candidates,
            s3,
            bucket,
            existing=existing,
            force=force,
            workers=worker_count,
            progress=progress,
            total=total,
            started=started,
            mirrored=mirrored,
            counters=counters,
            failed_items=failed_items,
        )

    # Preserve previously mirrored passcodes not present in this JSON slice
    # (e.g. test/limit runs) so the manifest never shrinks accidentally.
    previous = load_images_manifest(manifest_path)
    candidate_pids = {pid for pid, _ in candidates}
    mirrored |= previous - candidate_pids

    save_images_manifest(mirrored, manifest_path)
    log_line(f"Manifest written: {manifest_path} ({len(mirrored)} passcodes)")
    _write_failures(failed_items, manifest_path)
    log_line(
        f"[RESULT] total={total} uploaded={counters['uploaded']} "
        f"skipped={counters['skipped_existing']} no_image={counters['no_image']} "
        f"failed={counters['failed']}"
    )
    return counters


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mirror card images to S3-compatible storage")
    parser.add_argument("--json", type=Path, default=ALL_CARDS_PATH, help="Path to yugipedia_all_cards.json")
    parser.add_argument("--manifest", type=Path, default=IMAGES_MANIFEST_PATH, help="Manifest output path")
    parser.add_argument("--limit", type=int, default=None, help="Only process first N cards (testing)")
    parser.add_argument("--force", action="store_true", help="Re-download and re-upload existing objects")
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Parallel download/upload workers (default {DEFAULT_WORKERS})",
    )
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
        workers=args.workers,
    )
    if counters["failed"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
