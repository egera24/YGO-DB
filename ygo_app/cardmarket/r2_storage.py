"""Upload/download Cardmarket price export to private R2 object."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ygo_app import config
from ygo_app.cardmarket.paths import CARDMARKET_PRICES_PATH, R2_CARDMARKET_PRICES_KEY


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
        raise RuntimeError(f"Missing env vars for R2: {', '.join(missing)}")
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=config.S3_ENDPOINT_URL,
        aws_access_key_id=config.S3_ACCESS_KEY_ID,
        aws_secret_access_key=config.S3_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def upload_prices_file(
    local_path: Path = CARDMARKET_PRICES_PATH,
    *,
    object_key: str = R2_CARDMARKET_PRICES_KEY,
    keep_history: bool = True,
) -> str:
    if not local_path.is_file():
        raise FileNotFoundError(f"Price export not found: {local_path}")
    s3 = build_s3_client()
    bucket = config.S3_BUCKET
    assert bucket

    if keep_history:
        try:
            s3.head_object(Bucket=bucket, Key=object_key)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            history_key = f"catalog/cardmarket_prices/history/{ts}.json"
            s3.copy_object(
                Bucket=bucket,
                CopySource={"Bucket": bucket, "Key": object_key},
                Key=history_key,
            )
        except Exception:
            pass

    s3.upload_file(
        str(local_path),
        bucket,
        object_key,
        ExtraArgs={"ContentType": "application/json"},
    )
    return object_key


def download_prices_file(
    dest_path: Path = CARDMARKET_PRICES_PATH,
    *,
    object_key: str = R2_CARDMARKET_PRICES_KEY,
) -> Path:
    s3 = build_s3_client()
    bucket = config.S3_BUCKET
    assert bucket
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    s3.download_file(bucket, object_key, str(dest_path))
    return dest_path
