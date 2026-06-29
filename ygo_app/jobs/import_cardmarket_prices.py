"""Import Cardmarket catalog price export JSON into SCD Type 2 printing_market_prices."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from ygo_app.cardmarket.export_schema import load_export, validate_import_readiness
from ygo_app.cardmarket.market_prices import apply_scd_price_update, load_all_current_market_prices
from ygo_app.cardmarket.paths import CARDMARKET_PRICES_PATH
from ygo_app.cardmarket.r2_storage import download_latest_prices_archive
from ygo_app.database import SessionLocal
from ygo_app.import_data import init_db
from ygo_app.job_logging import run_job_logged
from ygo_app.yugipedia.scrape_progress import log_line

IMPORT_PROGRESS_EVERY = 5000
IMPORT_HEARTBEAT_SECONDS = 60


def compute_import_fingerprint(payload: dict) -> str:
    """SHA256 of sorted export price tuples for skip-if-unchanged."""
    parts: list[tuple] = []
    for item in payload["prices"]:
        parts.append(
            (
                item["set_code"],
                item["rarity_code"],
                item.get("low_price"),
                item.get("avg_price"),
                item.get("trend_price"),
                item.get("cardmarket_product_id"),
                item.get("cardmarket_url"),
                item.get("discovery_status"),
            )
        )
    parts.sort()
    digest = hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()
    return digest


def _load_last_fingerprint(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("fingerprint") or "") or None
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _save_fingerprint(path: Path, fingerprint: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"fingerprint": fingerprint}, indent=2),
        encoding="utf-8",
    )


def import_prices_from_payload(
    session,
    payload: dict,
    *,
    source_run_id: str | None = None,
    log_prefix: str = "[IMPORT]",
    fingerprint_path: Path | None = None,
    skip_if_unchanged: bool = False,
) -> dict[str, int]:
    stats: dict[str, int] = {
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "metadata_updated": 0,
    }
    prices = payload["prices"]
    total = len(prices)

    fingerprint = compute_import_fingerprint(payload)
    if skip_if_unchanged and fingerprint_path is not None:
        last = _load_last_fingerprint(fingerprint_path)
        if last == fingerprint:
            log_line(
                f"{log_prefix} import skipped unchanged "
                f"fingerprint={fingerprint[:16]}... rows={total}"
            )
            stats["skipped"] = total
            return stats

    run_start = time.monotonic()
    prefetch_start = time.monotonic()
    current_by_key = load_all_current_market_prices(session)
    prefetch_elapsed = time.monotonic() - prefetch_start
    log_line(
        f"{log_prefix} import prefetch current={len(current_by_key)} "
        f"rows={total} elapsed={prefetch_elapsed:.1f}s"
    )

    last_log_time = time.monotonic()
    for index, item in enumerate(prices, start=1):
        has_prices = any(
            item.get(k) is not None for k in ("low_price", "avg_price", "trend_price")
        )
        key = (item["set_code"], item["rarity_code"])
        _row, action = apply_scd_price_update(
            session,
            set_code=item["set_code"],
            rarity_code=item["rarity_code"],
            cardmarket_product_id=item.get("cardmarket_product_id"),
            cardmarket_url=item.get("cardmarket_url"),
            low_price=item.get("low_price"),
            avg_price=item.get("avg_price"),
            trend_price=item.get("trend_price"),
            discovery_status=item.get("discovery_status"),
            source_run_id=source_run_id,
            update_prices=has_prices,
            current=current_by_key.get(key),
        )
        stats[action] = stats.get(action, 0) + 1

        now = time.monotonic()
        if index % IMPORT_PROGRESS_EVERY == 0 or (now - last_log_time) >= IMPORT_HEARTBEAT_SECONDS:
            elapsed = now - run_start
            rate = index / elapsed if elapsed > 0 else 0.0
            remaining = total - index
            eta_min = (remaining / rate / 60) if rate > 0 else 0.0
            log_line(
                f"{log_prefix} import progress {index}/{total} "
                f"unchanged={stats['unchanged']} updated={stats['updated']} "
                f"inserted={stats['inserted']} rate={rate:.0f}/s eta={eta_min:.1f}m"
            )
            last_log_time = now

    session.commit()
    elapsed = time.monotonic() - run_start
    log_line(f"{log_prefix} import stats={json.dumps(stats)} elapsed={elapsed:.1f}s")

    if fingerprint_path is not None:
        _save_fingerprint(fingerprint_path, fingerprint)

    return stats


def run_import(
    *,
    file_path: Path,
    source_run_id: str | None = None,
) -> int:
    payload = load_export(file_path)
    gate = validate_import_readiness(payload)
    if not gate.ok:
        log_line("[IMPORT] import_gate FAILED")
        if gate.duplicates:
            log_line(f"duplicates={gate.duplicates}")
        if gate.missing_required:
            log_line(f"missing_required={gate.missing_required}")
        return 1
    for warning in gate.warnings:
        log_line(f"[IMPORT] import_gate warning: {warning}")

    log_line(f"[IMPORT] import_gate ok rows={len(payload['prices'])}")

    init_db()
    session = SessionLocal()
    try:
        import_prices_from_payload(session, payload, source_run_id=source_run_id)
        return 0
    finally:
        session.close()


def _run(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(description="Import Cardmarket price JSON into the database")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", "-f", type=Path, help="Local cardmarket_prices.json path")
    source.add_argument(
        "--from-r2",
        action="store_true",
        help="Download latest archives/cardmarket_prices_{ts}.zip from R2 then import",
    )
    parser.add_argument(
        "--download-path",
        type=Path,
        default=CARDMARKET_PRICES_PATH,
        help="Where to extract cardmarket_prices.json when using --from-r2",
    )
    parser.add_argument(
        "--run-ts",
        type=str,
        default=None,
        help="Import a specific R2 archive by timestamp suffix YYYYMMDD_HHMM",
    )
    parser.add_argument(
        "--source-run-id",
        type=str,
        default=None,
        help="Optional batch id stored on new SCD rows",
    )
    args = parser.parse_args(argv)

    path = args.file
    if args.from_r2:
        log_line("[IMPORT] downloading from R2")
        path = download_latest_prices_archive(args.download_path, run_ts=args.run_ts)
    assert path is not None
    return run_import(file_path=path, source_run_id=args.source_run_id)


def main(argv: list[str] | None = None) -> int:
    return run_job_logged(Path(__file__).stem, lambda: _run(argv))


if __name__ == "__main__":
    sys.exit(main())
