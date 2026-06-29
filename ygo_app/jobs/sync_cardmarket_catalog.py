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
from ygo_app.cardmarket.catalog.errors import CatalogDownloadError, CatalogPipelineError
from ygo_app.cardmarket.catalog.expansion_map import map_expansions_from_nonsingles
from ygo_app.cardmarket.catalog.pipeline_report import (
    CatalogRejection,
    PipelineReport,
    save_pipeline_report,
)
from ygo_app.cardmarket.catalog.printing_match import match_printings_to_catalog
from ygo_app.cardmarket.export_schema import (
    build_export_payload,
    save_export,
    validate_import_readiness,
)
from ygo_app.cardmarket.paths import CARDMARKET_PRICES_PATH, CARDMARKET_RAW_DIR
from ygo_app.cardmarket.r2_storage import (
    upload_catalog_archive,
    upload_pipeline_report,
    upload_prices_file,
    upload_run_log,
)
from ygo_app.database import SessionLocal
from ygo_app.import_data import init_db
from ygo_app.job_logging import job_log_session
from ygo_app.jobs.import_cardmarket_prices import import_prices_from_payload
from ygo_app.yugipedia.scrape_progress import log_line

def _utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _archive_ts(run_id: str) -> str:
    if len(run_id) > 10:
        return run_id.replace(":", "").replace("-", "")[:15]
    return _utc_run_id()


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


def _upload_run_artifacts(
    *,
    skip_r2: bool,
    archive_ts: str,
    log_path: Path | None,
    report_path: Path,
) -> dict[str, str | None]:
    keys: dict[str, str | None] = {
        "archive_key": None,
        "log_key": None,
        "report_key": None,
    }
    if skip_r2:
        return keys

    if log_path and log_path.is_file():
        try:
            keys["log_key"] = upload_run_log(log_path, timestamp=archive_ts)
            log_line(f"[CATALOG] uploaded run log to R2 key={keys['log_key']}")
        except RuntimeError as exc:
            log_line(f"[CATALOG] R2 run log upload skipped: {exc}")

    if report_path.is_file():
        try:
            keys["report_key"] = upload_pipeline_report(report_path, timestamp=archive_ts)
            log_line(f"[CATALOG] uploaded pipeline report to R2 key={keys['report_key']}")
        except RuntimeError as exc:
            log_line(f"[CATALOG] R2 pipeline report upload skipped: {exc}")

    return keys


def run_sync(
    *,
    download_only: bool = False,
    skip_import: bool = False,
    skip_r2: bool = False,
    raw_dir: Path = CARDMARKET_RAW_DIR,
    output_path: Path = CARDMARKET_PRICES_PATH,
    source_run_id: str | None = None,
    archive_ts: str | None = None,
) -> tuple[dict, PipelineReport, int]:
    run_id = source_run_id or os.getenv("GITHUB_RUN_ID") or _utc_run_id()
    ts = archive_ts or _archive_ts(run_id)
    report = PipelineReport(run_id=run_id, archive_ts=ts)
    exit_code = 0

    log_line(f"[CATALOG] run_id={run_id} archive_ts={ts}")

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
        "archive_ts": ts,
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
                timestamp=ts,
            )
            log_line(f"[CATALOG] archived to R2 key={archive_key}")
            report.r2_keys["archive_key"] = archive_key
        except RuntimeError as exc:
            log_line(f"[CATALOG] R2 archive skipped: {exc}")

    if download_only:
        result = {
            "run_id": run_id,
            "archive_ts": ts,
            "archive_key": archive_key,
            "download_only": True,
        }
        report.stats = result
        save_pipeline_report(raw_dir / "pipeline_report.json", report)
        return result, report, exit_code

    init_db()
    session = SessionLocal()
    import_stats: dict = {}
    match_stats: dict = {}
    payload: dict = {}

    try:
        nonsingles = load_products_json(download.nonsingles_path)
        singles = load_products_json(download.singles_path)
        prices = load_price_guide_json(download.price_guide_path)

        expansion_mappings, skipped_sets, expansion_rejections = map_expansions_from_nonsingles(
            session,
            nonsingles,
            singles=singles,
            price_rows=prices,
            upsert=True,
        )
        report.skipped_sets = skipped_sets
        report.rejections.extend(
            CatalogRejection.from_expansion_error(d) for d in expansion_rejections
        )
        log_line(f"[CATALOG] mapped expansions={len(expansion_mappings)}")
        log_line(f"[CATALOG] skipped sets={len(skipped_sets)}")
        log_line(f"[CATALOG] expansion rejections={len(expansion_rejections)}")

        export_rows, match_stats, printing_rejections = match_printings_to_catalog(
            session,
            singles=singles,
            price_rows=prices,
            expansion_mappings=expansion_mappings,
        )
        report.rejections.extend(
            CatalogRejection.from_printing_error(
                reason=str(d.get("reason") or "unknown"),
                set_code=str(d.get("set_code") or d.get("abbr") or ""),
                card_name=str(d.get("card_name") or ""),
                yugipedia_count=d.get("yugipedia_count"),
                cardmarket_count=d.get("cardmarket_count"),
            )
            for d in printing_rejections
        )
        session.commit()

        log_line(
            f"[CATALOG] printing rejections={len(printing_rejections)} "
            f"rejected_cards={match_stats.get('rejected_cards', 0)}"
        )

        payload = build_export_payload(export_rows)
        payload["stats"].update(match_stats)
        payload["stats"]["expansion_rejections"] = len(expansion_rejections)
        payload["stats"]["printing_rejections"] = len(printing_rejections)
        payload["stats"]["skipped_sets"] = len(skipped_sets)
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

        if not skip_import:
            gate = validate_import_readiness(payload)
            report.import_gate = gate
            if not gate.ok:
                exit_code = 1
                log_line("[CATALOG] import_gate FAILED")
                if gate.duplicates:
                    log_line(json.dumps({"duplicates": gate.duplicates}, indent=2))
                if gate.missing_required:
                    log_line(json.dumps({"missing_required": gate.missing_required}, indent=2))
            else:
                if gate.warnings:
                    for warning in gate.warnings:
                        log_line(f"[CATALOG] import_gate warning: {warning}")
                import_stats = import_prices_from_payload(
                    session,
                    payload,
                    source_run_id=str(run_id),
                )
                session.commit()
                log_line(f"[CATALOG] import stats={json.dumps(import_stats)}")

        result = {
            "run_id": run_id,
            "archive_ts": ts,
            "archive_key": archive_key,
            "export_path": str(output_path),
            "match_stats": match_stats,
            "import_stats": import_stats,
            "exported_at": payload.get("exported_at"),
            "rejection_counts": {
                "expansion": len(expansion_rejections),
                "printing": len(printing_rejections),
                "skipped_sets": len(skipped_sets),
            },
            "import_gate_ok": report.import_gate.ok if report.import_gate else None,
            "exit_code": exit_code,
        }
        report.stats = result
        save_pipeline_report(raw_dir / "pipeline_report.json", report)
        return result, report, exit_code
    finally:
        session.close()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
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
    return parser.parse_args(argv)


def _run(args: argparse.Namespace) -> int:
    run_id = args.source_run_id or os.getenv("GITHUB_RUN_ID") or _utc_run_id()
    archive_ts = _archive_ts(run_id)

    try:
        result, report, exit_code = run_sync(
            download_only=args.download_only,
            skip_import=args.skip_import,
            skip_r2=args.skip_r2,
            raw_dir=args.raw_dir,
            output_path=args.output,
            source_run_id=args.source_run_id,
            archive_ts=archive_ts,
        )
        summary_path = args.raw_dir / "sync_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return exit_code, archive_ts, args.raw_dir, report
    except CatalogDownloadError as exc:
        log_line(f"[CATALOG] DOWNLOAD FAILED: {exc}")
        return 1, archive_ts, args.raw_dir, None
    except CatalogPipelineError as exc:
        log_line(f"[CATALOG] FAILED: {exc}")
        if getattr(exc, "details", None):
            log_line(json.dumps(exc.details, indent=2))
        return 1, archive_ts, args.raw_dir, None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    log_path: Path | None = None

    with job_log_session(Path(__file__).stem) as handle:
        exit_code, archive_ts, raw_dir, report = _run(args)
        handle.exit_code = exit_code
        log_path = handle.path

    if log_path and not args.skip_r2:
        report_path = raw_dir / "pipeline_report.json"
        r2_keys = _upload_run_artifacts(
            skip_r2=False,
            archive_ts=archive_ts,
            log_path=log_path,
            report_path=report_path,
        )
        if report and (r2_keys.get("log_key") or r2_keys.get("report_key")):
            report.r2_keys.update({k: v for k, v in r2_keys.items() if v})
            save_pipeline_report(report_path, report)
            summary_path = raw_dir / "sync_summary.json"
            if summary_path.is_file():
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                summary["r2_keys"] = report.r2_keys
                summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
