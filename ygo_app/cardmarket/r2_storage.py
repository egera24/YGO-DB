"""Upload/download Cardmarket price export and catalog archives to R2."""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ygo_app import config
from ygo_app.cardmarket.archive_compression import (
    PRICES_EXPORT_MEMBER,
    brotli_compress_file,
    extract_prices_zip,
    write_lzma_zip,
)
from ygo_app.cardmarket.paths import (
    CARDMARKET_PRICES_PATH,
    LEGACY_R2_CARDMARKET_PRICES_KEY,
    PRICES_ARCHIVE_PREFIX,
    R2_CARDMARKET_ARCHIVE_PREFIX,
    prices_archive_key,
)

logger = logging.getLogger(__name__)

_cardmarket_bucket_warned = False


def _cardmarket_bucket() -> str:
    global _cardmarket_bucket_warned
    bucket = config.S3_CARDMARKET_BUCKET or config.S3_BUCKET
    if not bucket:
        raise RuntimeError(
            "Missing env var for Cardmarket R2: S3_CARDMARKET_BUCKET (or S3_BUCKET fallback)"
        )
    if not config.S3_CARDMARKET_BUCKET and not _cardmarket_bucket_warned:
        logger.warning(
            "S3_CARDMARKET_BUCKET not set — using S3_BUCKET for Cardmarket uploads"
        )
        _cardmarket_bucket_warned = True
    return bucket


def build_s3_client():
    missing = [
        name
        for name, value in (
            ("S3_ENDPOINT_URL", config.S3_ENDPOINT_URL),
            ("S3_ACCESS_KEY_ID", config.S3_ACCESS_KEY_ID),
            ("S3_SECRET_ACCESS_KEY", config.S3_SECRET_ACCESS_KEY),
        )
        if not value
    ]
    try:
        _cardmarket_bucket()
    except RuntimeError:
        missing.append("S3_CARDMARKET_BUCKET")
    if missing:
        raise RuntimeError(f"Missing env vars for R2: {', '.join(missing)}")
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=config.S3_ENDPOINT_URL,
        aws_access_key_id=config.S3_ACCESS_KEY_ID,
        aws_secret_access_key=config.S3_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def _list_prices_archive_keys(s3, bucket: str) -> list[str]:
    keys: list[str] = []
    continuation: str | None = None
    while True:
        kwargs: dict = {"Bucket": bucket, "Prefix": PRICES_ARCHIVE_PREFIX}
        if continuation:
            kwargs["ContinuationToken"] = continuation
        response = s3.list_objects_v2(**kwargs)
        for item in response.get("Contents") or []:
            key = item.get("Key")
            if key and key.endswith(".zip"):
                keys.append(key)
        if not response.get("IsTruncated"):
            break
        continuation = response.get("NextContinuationToken")
    return sorted(keys)


def _resolve_prices_archive_key(s3, bucket: str, run_ts: str | None) -> str | None:
    if run_ts:
        return prices_archive_key(run_ts)
    keys = _list_prices_archive_keys(s3, bucket)
    return keys[-1] if keys else None


def upload_prices_archive(
    local_path: Path = CARDMARKET_PRICES_PATH,
    *,
    run_ts: str,
) -> str:
    if not local_path.is_file():
        raise FileNotFoundError(f"Price export not found: {local_path}")

    object_key = prices_archive_key(run_ts)
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / f"cardmarket_prices_{run_ts}.zip"
        write_lzma_zip(
            zip_path,
            [(local_path, PRICES_EXPORT_MEMBER)],
        )
        s3 = build_s3_client()
        bucket = _cardmarket_bucket()
        s3.upload_file(
            str(zip_path),
            bucket,
            object_key,
            ExtraArgs={"ContentType": "application/zip"},
        )
    return object_key


def download_latest_prices_archive(
    dest_path: Path = CARDMARKET_PRICES_PATH,
    *,
    run_ts: str | None = None,
) -> Path:
    s3 = build_s3_client()
    bucket = _cardmarket_bucket()
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    object_key = _resolve_prices_archive_key(s3, bucket, run_ts)
    if object_key:
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "prices.zip"
            s3.download_file(bucket, object_key, str(zip_path))
            return extract_prices_zip(zip_path, dest_path)

    logger.warning(
        "No prices archive found under %s — falling back to legacy key %s",
        PRICES_ARCHIVE_PREFIX,
        LEGACY_R2_CARDMARKET_PRICES_KEY,
    )
    s3.download_file(bucket, LEGACY_R2_CARDMARKET_PRICES_KEY, str(dest_path))
    return dest_path


def upload_catalog_archive(
    *,
    singles_path: Path,
    nonsingles_path: Path,
    price_guide_path: Path,
    manifest: dict,
    run_ts: str | None = None,
) -> str:
    ts = run_ts or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    zip_path = singles_path.parent / f"catalog_archive_{ts}.zip"
    manifest_path = singles_path.parent / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    write_lzma_zip(
        zip_path,
        [
            (singles_path, singles_path.name),
            (nonsingles_path, nonsingles_path.name),
            (price_guide_path, price_guide_path.name),
            (manifest_path, "manifest.json"),
        ],
    )

    object_key = f"{R2_CARDMARKET_ARCHIVE_PREFIX}/catalog_archive_{ts}.zip"
    s3 = build_s3_client()
    bucket = _cardmarket_bucket()
    s3.upload_file(
        str(zip_path),
        bucket,
        object_key,
        ExtraArgs={"ContentType": "application/zip"},
    )
    return object_key


def upload_run_log(
    log_path: Path,
    *,
    run_ts: str,
) -> str:
    if not log_path.is_file():
        raise FileNotFoundError(f"Job log not found: {log_path}")
    object_key = f"{R2_CARDMARKET_ARCHIVE_PREFIX}/sync_price_log_{run_ts}.log.br"
    compressed = brotli_compress_file(log_path)
    s3 = build_s3_client()
    bucket = _cardmarket_bucket()
    s3.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=compressed,
        ContentType="application/octet-stream",
    )
    return object_key


def upload_pipeline_report(
    report_path: Path,
    *,
    run_ts: str,
) -> str:
    if not report_path.is_file():
        raise FileNotFoundError(f"Pipeline report not found: {report_path}")
    object_key = f"{R2_CARDMARKET_ARCHIVE_PREFIX}/sync_price_report_{run_ts}.json.br"
    compressed = brotli_compress_file(report_path)
    s3 = build_s3_client()
    bucket = _cardmarket_bucket()
    s3.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=compressed,
        ContentType="application/octet-stream",
    )
    return object_key
