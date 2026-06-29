"""Sync Cardmarket official catalog JSON → Yugipedia match → SCD import."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from ygo_app.cardmarket.catalog.download import (
    download_catalog,
    load_price_guide_json,
    load_products_json,
)
from ygo_app.cardmarket.catalog.errors import CatalogPipelineError
from ygo_app.cardmarket.catalog.expansion_map import map_expansions_from_nonsingles
from ygo_app.cardmarket.catalog.printing_match import match_printings_to_catalog
from ygo_app.cardmarket.export_schema import build_export_payload, save_export
from ygo_app.cardmarket.paths import CARDMARKET_PRICES_PATH, CARDMARKET_RAW_DIR
from ygo_app.cardmarket.r2_storage import upload_catalog_archive, upload_prices_file
from ygo_app.database import SessionLocal
from ygo_app.import_data import init_db
from ygo_app.job_logging import run_job_logged
from ygo_app.jobs.import_cardmarket_prices import import_prices_from_payload
from ygo_app.yugipedia.scrape_progress import log_line


def _utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_html_fixtures() -> list[str]:
    fixtures: list[str] = []
    repo_root = Path(__file__).resolve().parents[2]
    for name in (
        "DO NOT DELETE/cardmarket_product_catalog_html_code.html",
        "DO NOT DELETE/cardmarket_price_guides_html_code.html",
    ):
        path = repo_root / name
        if path.is_file():
            fixtures.append(path.read_text(encoding="utf-8", errors="replace"))
    return fixtures


def run_sync(
    *,
    download_only: bool = False,
    skip_import: bool = False,
    skip_r2: bool = False,
    raw_dir: Path = CARDMARKET_RAW_DIR,
    output_path: Path = CARDMARKET_PRICES_PATH,
    source_run_id: str | None = None,
) -> dict:
    run_id = source_run_id or os.getenv("GITHUB_RUN_ID") or _utc_run_id()
    log_line(f"[CATALOG] run_id={run_id}")

    html_sources = _load_html_fixtures()
    download = download_catalog(output_dir=raw_dir, html_sources=html_sources)
    log_line(
        f"[CATALOG] downloaded singles={download.row_counts['singles']} "
        f"nonsingles={download.row_counts['nonsingles']} "
        f"prices={download.row_counts['price_guide']}"
    )

    manifest = {
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "run_id": run_id,
        "urls": download.urls,
        "sha256": download.sha256,
        "row_counts": download.row_counts,
    }

    archive_key = None
    if not skip_r2:
        try:
            archive_key = upload_catalog_archive(
                singles_path=download.singles_path,
                nonsingles_path=download.nonsingles_path,
                price_guide_path=download.price_guide_path,
                manifest=manifest,
                timestamp=run_id.replace(":", "").replace("-", "")[:15] if len(run_id) > 10 else None,
            )
            log_line(f"[CATALOG] archived to R2 key={archive_key}")
        except RuntimeError as exc:
            log_line(f"[CATALOG] R2 archive skipped: {exc}")

    if download_only:
        return {"run_id": run_id, "archive_key": archive_key, "download_only": True}

    init_db()
    session = SessionLocal()
    try:
        nonsingles = load_products_json(download.nonsingles_path)
        singles = load_products_json(download.singles_path)
        prices = load_price_guide_json(download.price_guide_path)

        expansion_mappings, skipped_sets = map_expansions_from_nonsingles(
            session,
            nonsingles,
            singles=singles,
            price_rows=prices,
            upsert=True,
        )
        log_line(f"[CATALOG] mapped expansions={len(expansion_mappings)}")
        log_line(f"[CATALOG] skipped sets={len(skipped_sets)}")

        export_rows, match_stats = match_printings_to_catalog(
            session,
            singles=singles,
            price_rows=prices,
            expansion_mappings=expansion_mappings,
        )
        session.commit()

        payload = build_export_payload(export_rows)
        payload["stats"].update(match_stats)
        save_export(output_path, payload)
        log_line(
            f"[CATALOG] export rows={len(export_rows)} matched={match_stats['matched']} "
            f"cards_processed={match_stats['cards_processed']}"
        )

        if not skip_r2:
            try:
                upload_prices_file(output_path)
                log_line("[CATALOG] uploaded latest export to R2")
            except RuntimeError as exc:
                log_line(f"[CATALOG] R2 export upload skipped: {exc}")

        import_stats = {}
        if not skip_import:
            import_stats = import_prices_from_payload(
                session,
                payload,
                source_run_id=str(run_id),
            )
            session.commit()
            log_line(f"[CATALOG] import stats={json.dumps(import_stats)}")

        return {
            "run_id": run_id,
            "archive_key": archive_key,
            "export_path": str(output_path),
            "match_stats": match_stats,
            "import_stats": import_stats,
            "exported_at": payload.get("exported_at"),
        }
    finally:
        session.close()


def _run(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(description="Sync Cardmarket catalog JSON to Neon")
    parser.add_argument("--download-only", action="store_true", help="Download + archive only")
    parser.add_argument("--skip-import", action="store_true", help="Match/export but skip DB import")
    parser.add_argument("--skip-r2", action="store_true", help="Skip R2 upload (local dev)")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=CARDMARKET_PRICES_PATH,
        help="Export JSON output path",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=CARDMARKET_RAW_DIR,
        help="Directory for downloaded raw JSON",
    )
    parser.add_argument(
        "--source-run-id",
        type=str,
        default=None,
        help="Batch id for SCD rows (defaults to timestamp or GITHUB_RUN_ID)",
    )
    args = parser.parse_args(argv)

    try:
        result = run_sync(
            download_only=args.download_only,
            skip_import=args.skip_import,
            skip_r2=args.skip_r2,
            raw_dir=args.raw_dir,
            output_path=args.output,
            source_run_id=args.source_run_id,
        )
        summary_path = args.raw_dir / "sync_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 0
    except CatalogPipelineError as exc:
        log_line(f"[CATALOG] FAILED: {exc}")
        if getattr(exc, "details", None):
            log_line(json.dumps(exc.details, indent=2))
        return 1


def main(argv: list[str] | None = None) -> int:
    return run_job_logged(Path(__file__).stem, lambda: _run(argv))


if __name__ == "__main__":
    sys.exit(main())
