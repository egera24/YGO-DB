"""Import Cardmarket catalog price export JSON into SCD Type 2 printing_market_prices."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ygo_app.cardmarket.export_schema import load_export, validate_import_readiness
from ygo_app.cardmarket.market_prices import apply_scd_price_update
from ygo_app.cardmarket.paths import CARDMARKET_PRICES_PATH
from ygo_app.cardmarket.r2_storage import download_latest_prices_archive
from ygo_app.database import SessionLocal
from ygo_app.import_data import init_db
from ygo_app.job_logging import run_job_logged
from ygo_app.yugipedia.scrape_progress import log_line


def import_prices_from_payload(
    session,
    payload: dict,
    *,
    source_run_id: str | None = None,
) -> dict[str, int]:
    stats = {"inserted": 0, "updated": 0, "unchanged": 0, "metadata_updated": 0}
    for item in payload["prices"]:
        has_prices = any(
            item.get(k) is not None for k in ("low_price", "avg_price", "trend_price")
        )
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
        )
        stats[action] = stats.get(action, 0) + 1
    session.commit()
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

    init_db()
    session = SessionLocal()
    try:
        stats = import_prices_from_payload(session, payload, source_run_id=source_run_id)
        log_line(
            f"[IMPORT] inserted={stats.get('inserted', 0)} updated={stats.get('updated', 0)} "
            f"unchanged={stats.get('unchanged', 0)} metadata={stats.get('metadata_updated', 0)} "
            f"total_rows={len(payload['prices'])} exported_at={payload.get('exported_at')}"
        )
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
