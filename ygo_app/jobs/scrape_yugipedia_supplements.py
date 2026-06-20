"""Scrape Yugipedia errata and tips pages for catalog cards."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path

from ygo_app.yugipedia.constants import (
    CHECKPOINT_EVERY,
    MAX_WORKERS,
    PER_CARD_POOL_TIMEOUT_SECONDS,
    SUPPLEMENT_PROBE_RETRIES,
    SUPPLEMENT_PROBE_TIMEOUT,
)
from ygo_app.yugipedia.details import slice_input_cards_for_batch
from ygo_app.yugipedia.errata import compute_errata_flags, parse_errata_html
from ygo_app.yugipedia.http_client import create_scraper, fetch_page
from ygo_app.yugipedia.paths import ALL_CARDS_PATH, SET_CHRONOLOGY_PATH, ensure_catalog_dir
from ygo_app.yugipedia.related_links import (
    errata_url_for_card_name,
    is_missing_supplement_page_error,
    tips_url_for_card_name,
)
from ygo_app.yugipedia.scrape_progress import ScrapeProgressMonitor, log_line

from ygo_app.yugipedia.tips import parse_tips_html


def _supplement_page_url(
    card: dict,
    field: str,
    name: str,
    builder,
) -> str | None:
    """Return stored link from detail scrape, or legacy canonical URL if key absent."""
    if field in card:
        return card.get(field)
    return builder(name)


def _load_json_list(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_cards(path: Path, cards: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(cards, f, indent=2, ensure_ascii=False)


def _load_set_release_lookup(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    rows = _load_json_list(path)
    lookup: dict[str, str] = {}
    for row in rows:
        abbr = row.get("abbr")
        release = row.get("release_date")
        if abbr and release:
            lookup[str(abbr).upper()] = release
    return lookup


def _cards_with_supplements_done(
    cards: list[dict],
    *,
    scrape_errata: bool,
    scrape_tips: bool,
    force_tips: bool = False,
) -> set[str]:
    done: set[str] = set()
    for card in cards:
        pid = str(card.get("id", "")).zfill(8)
        errata_ok = not scrape_errata or "errata" in card
        tips_ok = not scrape_tips or ("tips" in card and not force_tips)
        if errata_ok and tips_ok:
            done.add(pid)
    return done


def _merge_card_updates(existing: list[dict], updates: dict[str, dict]) -> list[dict]:
    merged: list[dict] = []
    for card in existing:
        pid = str(card.get("id", "")).zfill(8)
        if pid in updates:
            merged.append({**card, **updates[pid]})
        else:
            merged.append(card)
    return merged


def _fetch_supplement_html(scraper, url: str) -> tuple[str | None, str | None]:
    """Fetch errata/tips page; short timeout, no retry loop for missing pages."""
    return fetch_page(
        scraper,
        url,
        retries=SUPPLEMENT_PROBE_RETRIES,
        timeout=SUPPLEMENT_PROBE_TIMEOUT,
    )


def _process_supplements(
    scraper,
    card: dict,
    *,
    set_release_lookup: dict[str, str],
    scrape_errata: bool,
    scrape_tips: bool,
) -> dict:
    name = card.get("name") or ""
    update: dict = {}

    if scrape_errata:
        errata_url = _supplement_page_url(card, "errata_url", name, errata_url_for_card_name)
        if not errata_url:
            update["errata"] = []
            update["has_errata"] = False
        else:
            html, error = _fetch_supplement_html(scraper, errata_url)
            if html and "card-errata" in html:
                versions = parse_errata_html(html, set_release_lookup=set_release_lookup)
                if versions:
                    update["errata"] = versions
                    has_errata, last_date = compute_errata_flags(versions)
                    update["has_errata"] = has_errata
                    if last_date:
                        update["last_erratum_date"] = last_date
                    else:
                        update["has_errata"] = len(versions) > 1 or any(
                            v.get("version_index", 0) > 0 for v in versions
                        )
                else:
                    update["errata"] = []
                    update["has_errata"] = False
            elif error and not is_missing_supplement_page_error(error):
                return {"success": False, "card": card, "error": error}
            else:
                update["errata"] = []
                update["has_errata"] = False

    if scrape_tips:
        tips_url = _supplement_page_url(card, "tips_url", name, tips_url_for_card_name)
        if not tips_url:
            update["tips"] = []
        else:
            html, error = _fetch_supplement_html(scraper, tips_url)
            if html and 'id="mw-content-text"' in html:
                tips = parse_tips_html(html)
                update["tips"] = tips
            elif error and not is_missing_supplement_page_error(error):
                return {"success": False, "card": card, "error": error}
            else:
                update["tips"] = []

    return {"success": True, "card": card, "update": update}


def scrape_supplements(
    *,
    cards_path: Path = ALL_CARDS_PATH,
    set_chronology_path: Path = SET_CHRONOLOGY_PATH,
    batch_index: int | None = None,
    batch_count: int | None = None,
    resume: bool = False,
    max_cards: int | None = None,
    scrape_errata: bool = True,
    scrape_tips: bool = True,
    force_tips: bool = False,
) -> None:
    ensure_catalog_dir()
    if not cards_path.exists():
        raise FileNotFoundError(f"Catalog not found: {cards_path}")

    catalog_cards = _load_json_list(cards_path)
    work_cards = catalog_cards[:max_cards] if max_cards is not None else catalog_cards

    slice_cards = work_cards
    if batch_index is not None and batch_count is not None:
        slice_cards = slice_input_cards_for_batch(work_cards, batch_index, batch_count)

    done_ids = (
        _cards_with_supplements_done(
            catalog_cards,
            scrape_errata=scrape_errata,
            scrape_tips=scrape_tips,
            force_tips=force_tips,
        )
        if resume
        else set()
    )
    pending = [c for c in slice_cards if str(c.get("id", "")).zfill(8) not in done_ids]

    set_release_lookup = _load_set_release_lookup(set_chronology_path)
    force_part = " force_tips=True" if force_tips else ""
    log_line(
        f"[SUPPLEMENTS] pending={len(pending)} slice={len(slice_cards)} "
        f"catalog={len(catalog_cards)} errata={scrape_errata} tips={scrape_tips}{force_part}"
    )

    if not pending:
        log_line("[SUPPLEMENTS] nothing to scrape")
        return

    updates_by_id: dict[str, dict] = {}
    lock = threading.Lock()
    monitor = ScrapeProgressMonitor(total_pending=len(pending), output_path=cards_path)
    monitor.start()
    scrapers = [create_scraper() for _ in range(MAX_WORKERS)]
    completed = 0

    def handle_result(result: dict) -> bool:
        nonlocal completed
        card = result["card"]
        pid = str(card.get("id", "")).zfill(8)
        name = card.get("name") or pid
        if not result["success"]:
            log_line(f"[SUPPLEMENTS FAIL] {pid} — {result.get('error', '?')}")
            return False
        with lock:
            updates_by_id[pid] = result.get("update", {})
            completed += 1
            if completed % CHECKPOINT_EVERY == 0:
                merged = _merge_card_updates(catalog_cards, updates_by_id)
                _save_cards(cards_path, merged)
        monitor.record(card_name=name, success=True)
        return True

    work_index = 0
    total = len(pending)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        in_flight: dict[Future, dict] = {}

        def submit_next() -> None:
            nonlocal work_index
            while work_index < total and len(in_flight) < MAX_WORKERS:
                card = pending[work_index]
                scraper = scrapers[work_index % len(scrapers)]
                fut = executor.submit(
                    _process_supplements,
                    scraper,
                    card,
                    set_release_lookup=set_release_lookup,
                    scrape_errata=scrape_errata,
                    scrape_tips=scrape_tips,
                )
                in_flight[fut] = card
                work_index += 1

        submit_next()
        while in_flight:
            monitor.check_abort()
            done, _ = wait(
                in_flight,
                return_when=FIRST_COMPLETED,
                timeout=PER_CARD_POOL_TIMEOUT_SECONDS,
            )
            if not done:
                stuck_names = ", ".join(
                    (c.get("name") or str(c.get("id", "")))[:24] for c in in_flight.values()
                )
                log_line(
                    f"[SUPPLEMENTS WARN] pool timeout; saving checkpoint "
                    f"({len(in_flight)} in-flight: {stuck_names})"
                )
                break
            for fut in done:
                in_flight.pop(fut)
                try:
                    result = fut.result(timeout=1)
                except Exception as exc:
                    card = pending[0]
                    result = {"success": False, "card": card, "error": str(exc)}
                handle_result(result)
            submit_next()

    merged = _merge_card_updates(catalog_cards, updates_by_id)
    _save_cards(cards_path, merged)
    monitor.stop()
    log_line(f"[SUPPLEMENTS] done updates={len(updates_by_id)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Yugipedia errata/tips supplements")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--batch-index", type=int, default=None)
    parser.add_argument("--batch-count", type=int, default=None)
    parser.add_argument("--max-cards", type=int, default=None)
    parser.add_argument("--errata-only", action="store_true")
    parser.add_argument("--tips-only", action="store_true")
    parser.add_argument("--force-tips", action="store_true", help="Re-scrape tips even when already present")
    parser.add_argument("--json", type=Path, default=ALL_CARDS_PATH)
    args = parser.parse_args(argv)

    scrape_errata = not args.tips_only
    scrape_tips = not args.errata_only
    if args.errata_only:
        scrape_tips = False
    if args.tips_only:
        scrape_errata = False

    try:
        scrape_supplements(
            cards_path=args.json,
            batch_index=args.batch_index,
            batch_count=args.batch_count,
            resume=args.resume,
            max_cards=args.max_cards,
            scrape_errata=scrape_errata,
            scrape_tips=scrape_tips,
            force_tips=args.force_tips,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
