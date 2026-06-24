"""Upload local Cardmarket price export JSON to private R2 object."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ygo_app.cardmarket.export_schema import load_export
from ygo_app.cardmarket.paths import CARDMARKET_PRICES_PATH
from ygo_app.cardmarket.r2_storage import upload_prices_file
from ygo_app.job_logging import run_job_logged
from ygo_app.yugipedia.scrape_progress import log_line


def _run(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(description="Upload Cardmarket price JSON to R2")
    parser.add_argument(
        "--file",
        "-f",
        type=Path,
        default=CARDMARKET_PRICES_PATH,
        help="Local export file (default: data/catalog/cardmarket_prices.json)",
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="Do not copy previous R2 object to history/ before overwrite",
    )
    args = parser.parse_args(argv)

    payload = load_export(args.file)
    key = upload_prices_file(args.file, keep_history=not args.no_history)
    log_line(
        f"[UPLOAD] {args.file} → s3://…/{key} "
        f"(rows={payload['stats']['total']} exported_at={payload['exported_at']})"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_job_logged(Path(__file__).stem, lambda: _run(argv))


if __name__ == "__main__":
    sys.exit(main())
