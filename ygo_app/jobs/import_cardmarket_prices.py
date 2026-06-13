"""Import Cardmarket price export JSON into Neon/SQLite printing_market_prices."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ygo_app.cardmarket.export_schema import load_export
from ygo_app.cardmarket.market_prices import upsert_market_price
from ygo_app.cardmarket.paths import CARDMARKET_PRICES_PATH
from ygo_app.cardmarket.r2_storage import download_prices_file
from ygo_app.database import SessionLocal
from ygo_app.import_data import init_db
from ygo_app.models import PrintingMarketPrice
from ygo_app.yugipedia.scrape_progress import log_line


def import_prices_from_payload(session, payload: dict) -> dict[str, int]:
    stats = {"inserted": 0, "updated": 0}
    for item in payload["prices"]:
        set_code = item["set_code"]
        rarity_code = item["rarity_code"]
        existed = (
            session.get(PrintingMarketPrice, {"set_code": set_code, "rarity_code": rarity_code})
            is not None
        )
        has_prices = any(
            item.get(k) is not None for k in ("low_price", "avg_price", "trend_price")
        )
        upsert_market_price(
            session,
            set_code=set_code,
            rarity_code=rarity_code,
            cardmarket_product_id=item.get("cardmarket_product_id"),
            cardmarket_url=item.get("cardmarket_url"),
            low_price=item.get("low_price"),
            avg_price=item.get("avg_price"),
            trend_price=item.get("trend_price"),
            discovery_status=item.get("discovery_status"),
            update_prices=has_prices,
        )
        if existed:
            stats["updated"] += 1
        else:
            stats["inserted"] += 1
    session.commit()
    return stats


def run_import(*, file_path: Path) -> int:
    payload = load_export(file_path)
    init_db()
    session = SessionLocal()
    try:
        stats = import_prices_from_payload(session, payload)
        log_line(
            f"[IMPORT] inserted={stats['inserted']} updated={stats['updated']} "
            f"total_rows={len(payload['prices'])} exported_at={payload.get('exported_at')}"
        )
        return 0
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import Cardmarket price JSON into the database")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", "-f", type=Path, help="Local cardmarket_prices.json path")
    source.add_argument(
        "--from-r2",
        action="store_true",
        help="Download catalog/cardmarket_prices.json from R2 then import",
    )
    parser.add_argument(
        "--download-path",
        type=Path,
        default=CARDMARKET_PRICES_PATH,
        help="Where to save R2 object when using --from-r2",
    )
    args = parser.parse_args(argv)

    path = args.file
    if args.from_r2:
        log_line("[IMPORT] downloading from R2")
        path = download_prices_file(args.download_path)
    assert path is not None
    return run_import(file_path=path)


if __name__ == "__main__":
    sys.exit(main())
