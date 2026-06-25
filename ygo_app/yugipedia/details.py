"""Scrape Yugipedia card detail pages into yugipedia_all_cards.json."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path

from ygo_app.yugipedia.constants import (
    CHECKPOINT_EVERY,
    FAILED_RETRY_ROUNDS,
    MAX_WORKERS,
    PER_CARD_POOL_TIMEOUT_SECONDS,
    PROGRESS_LOG_EVERY,
    REQUESTS_PER_SECOND,
)
from ygo_app.yugipedia.http_client import create_scraper, fetch_page
from ygo_app.yugipedia.passcodes import limit_passcode_list
from ygo_app.yugipedia.parsing import parse_card_page
from ygo_app.yugipedia.paths import (
    ALL_CARDS_PATH,
    PASSCODE_LIST_PATH,
    REJECTED_PATH,
    ensure_catalog_dir,
)
from ygo_app.yugipedia.scrape_progress import (
    BatchIncompleteError,
    ScrapeProgressMonitor,
    ScrapeStalledError,
    is_retryable_error,
    log_line,
)


def _load_json_list(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _passwords_done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    cards = _load_json_list(path)
    done: set[str] = set()
    for c in cards:
        pid = c.get("id")
        if pid is not None:
            done.add(str(pid).zfill(8))
    return done


def _save_cards(path: Path, cards: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(cards, f, indent=2, ensure_ascii=False)


def _save_rejected(path: Path, rejected: list[dict]) -> None:
    payload = {
        "timestamp": datetime.now().isoformat(),
        "total_rejected": len(rejected),
        "rejected_cards": rejected,
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def slice_input_cards_for_batch(
    input_cards: list[dict],
    batch_index: int,
    batch_count: int,
) -> list[dict]:
    """Return a contiguous slice of the passcode list for GHA batch jobs."""
    if batch_count < 1:
        raise ValueError(f"batch_count must be >= 1, got {batch_count}")
    if batch_index < 0 or batch_index >= batch_count:
        raise ValueError(
            f"batch_index must be in [0, {batch_count - 1}], got {batch_index}"
        )
    n = len(input_cards)
    start = n * batch_index // batch_count
    end = n * (batch_index + 1) // batch_count
    return input_cards[start:end]


def audit_slice_completion(
    *,
    slice_cards: list[dict],
    output_path: Path,
    rejected_cards: list[dict],
    batch_index: int | None,
    batch_count: int | None,
) -> int:
    """
    Log [BATCH_RESULT] and return missing passcode count for this slice.
    Raises BatchIncompleteError when batch_index is set and missing > 0.
    """
    slice_passwords = {str(c["password"]).zfill(8) for c in slice_cards}
    saved = _passwords_done(output_path)
    rejected_pw = {
        str(c.get("password", "")).zfill(8)
        for c in rejected_cards
        if c.get("password")
    }
    missing = slice_passwords - saved - rejected_pw
    saved_in_slice = len(slice_passwords & saved)
    rejected_in_slice = len(slice_passwords & rejected_pw)

    if batch_index is not None and batch_count is not None:
        label = f"batch={batch_index + 1}/{batch_count}"
    else:
        label = "scope=full"

    log_line(
        f"[BATCH_RESULT] {label} expected={len(slice_passwords)} "
        f"saved={saved_in_slice} rejected={rejected_in_slice} missing={len(missing)}"
    )
    if missing:
        sample = ", ".join(sorted(missing)[:5])
        more = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
        log_line(f"[BATCH_RESULT] missing passcodes (sample): {sample}{more}")

    if missing and batch_index is not None:
        raise BatchIncompleteError(
            f"Batch {batch_index + 1}/{batch_count} incomplete: "
            f"{len(missing)} of {len(slice_passwords)} passcodes not saved or rejected. "
            "Re-run with --resume after fixing connectivity."
        )
    if missing and batch_index is None:
        log_line(
            f"[WARN] Scrape scope incomplete: {len(missing)} passcodes not saved or rejected"
        )
    return len(missing)


def _process_card(scraper, input_card: dict) -> dict:
    html, error = fetch_page(scraper, input_card["url"])
    if html is None:
        return {"success": False, "input_card": input_card, "error": error}
    card_data, parse_error = parse_card_page(html, input_card)
    if parse_error:
        return {"success": False, "input_card": input_card, "error": parse_error}
    if not card_data.get("card_sets"):
        return {
            "success": False,
            "input_card": input_card,
            "error": "No English (TCG) printings",
        }
    return {"success": True, "card_data": card_data, "input_card": input_card}


def _log_fail(card: dict, error: str, *, will_retry: bool) -> None:
    tag = "will-retry" if will_retry else "final"
    name = (card.get("name") or "?")[:30]
    password = str(card.get("password", "")).zfill(8)
    log_line(f"[FAIL] {tag} {password} {name} — {error}")


def _reject_card(card: dict, error: str, rejected_cards: list[dict]) -> None:
    entry = card.copy()
    entry["rejection_reason"] = error
    entry["rejection_timestamp"] = datetime.now().isoformat()
    rejected_cards.append(entry)


def _handle_scrape_result(
    result: dict,
    *,
    successful_cards: list[dict],
    rejected_cards: list[dict],
    retryable_failures: list[tuple[dict, str]],
) -> bool:
    """Apply result; queue retryable failures. Returns True if success."""
    input_card = result["input_card"]
    if result["success"]:
        successful_cards.append(result["card_data"])
        return True

    error = result.get("error", "unknown") or "unknown"
    if is_retryable_error(error):
        retryable_failures.append((input_card, error))
        _log_fail(input_card, error, will_retry=True)
        return False

    _log_fail(input_card, error, will_retry=False)
    _reject_card(input_card, error, rejected_cards)
    return False


def _scrape_pending_bounded(
    pending: list[dict],
    *,
    scrapers: list,
    successful_cards: list[dict],
    rejected_cards: list[dict],
    output_path: Path,
    monitor: ScrapeProgressMonitor,
    checkpoint_every: int,
    lock: threading.Lock,
    run_start: float,
    round_label: str,
    use_monitor: bool = True,
) -> tuple[list[tuple[dict, str]], list[tuple[dict, str]]]:
    """
    Scrape pending cards with at most MAX_WORKERS in flight.

    Returns (pool_timeout_items, retryable_failure_items) as (card, error) pairs.
    """
    if not pending:
        return [], []

    pool_timeout_items: list[tuple[dict, str]] = []
    retryable_failures: list[tuple[dict, str]] = []
    pool_msg = f"PoolTimeout: no completion within {PER_CARD_POOL_TIMEOUT_SECONDS}s"
    work_index = 0
    total = len(pending)

    def maybe_checkpoint(completed: int) -> None:
        if completed > 0 and completed % checkpoint_every == 0:
            with lock:
                _save_cards(output_path, successful_cards)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        in_flight: dict[Future, dict] = {}

        def submit_next() -> None:
            nonlocal work_index
            while work_index < total and len(in_flight) < MAX_WORKERS:
                card = pending[work_index]
                scraper = scrapers[work_index % len(scrapers)]
                fut = executor.submit(_process_card, scraper, card)
                in_flight[fut] = card
                work_index += 1

        submit_next()

        while in_flight:
            if use_monitor:
                monitor.check_abort()
            done, _ = wait(
                in_flight,
                return_when=FIRST_COMPLETED,
                timeout=PER_CARD_POOL_TIMEOUT_SECONDS,
            )

            if not done:
                log_line(
                    f"[WARN] Pool idle {PER_CARD_POOL_TIMEOUT_SECONDS}s with "
                    f"{len(in_flight)} in-flight ({round_label}); re-queueing for retry"
                )
                for card in in_flight.values():
                    pool_timeout_items.append((card, pool_msg))
                if work_index < total:
                    for card in pending[work_index:]:
                        pool_timeout_items.append((card, pool_msg))
                    work_index = total
                for fut in in_flight:
                    fut.cancel()
                in_flight.clear()
                break

            for fut in done:
                card = in_flight.pop(fut)
                try:
                    result = fut.result(timeout=1)
                except Exception as exc:
                    result = {
                        "success": False,
                        "input_card": card,
                        "error": f"WorkerError: {type(exc).__name__}: {exc!s}"[:120],
                    }

                success = False
                with lock:
                    success = _handle_scrape_result(
                        result,
                        successful_cards=successful_cards,
                        rejected_cards=rejected_cards,
                        retryable_failures=retryable_failures,
                    )

                if use_monitor:
                    monitor.record(card_name=card.get("name", "?"), success=success)
                    completed_this_round = monitor.completed
                    if (
                        completed_this_round % PROGRESS_LOG_EVERY == 0
                        or completed_this_round == monitor.total_pending
                    ):
                        monitor.log_progress_line(
                            completed=completed_this_round,
                            total=monitor.total_pending,
                            card_name=card.get("name", "?"),
                            success=success,
                            run_start=run_start,
                        )
                    maybe_checkpoint(completed_this_round)
                    monitor.check_abort()
                submit_next()

    return pool_timeout_items, retryable_failures


def _merge_retry_items(
    pool_items: list[tuple[dict, str]],
    failure_items: list[tuple[dict, str]],
) -> list[tuple[dict, str]]:
    by_password: dict[str, tuple[dict, str]] = {}
    for card, error in pool_items + failure_items:
        by_password[str(card["password"]).zfill(8)] = (card, error)
    return list(by_password.values())


def scrape_card_details(
    *,
    input_path: Path | None = None,
    output_path: Path | None = None,
    rejected_path: Path | None = None,
    resume: bool = False,
    batch_index: int | None = None,
    batch_count: int | None = None,
    max_cards: int | None = None,
    checkpoint_every: int = CHECKPOINT_EVERY,
    failed_retry_rounds: int = FAILED_RETRY_ROUNDS,
) -> tuple[Path, Path, int, int]:
    """
    Scrape card pages from passcode list.

    When batch_index and batch_count are set, only the corresponding slice of
    the passcode list is scraped (for chained GHA jobs).

    Returns (output_path, rejected_path, success_count, rejected_count).
    """
    ensure_catalog_dir()
    input_path = input_path or PASSCODE_LIST_PATH
    output_path = output_path or ALL_CARDS_PATH
    rejected_path = rejected_path or REJECTED_PATH

    if (batch_index is None) != (batch_count is None):
        raise ValueError("batch_index and batch_count must both be set or both omitted")

    if not input_path.exists():
        raise FileNotFoundError(f"Passcode list not found: {input_path}")

    input_cards = limit_passcode_list(_load_json_list(input_path), max_cards)
    total_in_list = len(input_cards)
    slice_cards = input_cards

    if batch_index is not None:
        assert batch_count is not None
        slice_cards = slice_input_cards_for_batch(input_cards, batch_index, batch_count)
        log_line(
            f"Batch {batch_index + 1}/{batch_count}: "
            f"slice {len(slice_cards)} of {total_in_list} passcodes"
        )

    done_passwords: set[str] = set()
    successful_cards: list[dict] = []

    if resume and output_path.exists():
        successful_cards = _load_json_list(output_path)
        done_passwords = _passwords_done(output_path)
        log_line(f"Resume: {len(done_passwords)} cards already scraped")

    pending = [c for c in slice_cards if c["password"] not in done_passwords]
    rejected_cards: list[dict] = []
    if rejected_path.exists():
        try:
            with rejected_path.open("r", encoding="utf-8") as f:
                prev = json.load(f)
            if isinstance(prev, dict) and "rejected_cards" in prev:
                rejected_cards = list(prev["rejected_cards"])
        except (json.JSONDecodeError, OSError):
            rejected_cards = []

    log_line(f"Input: {len(slice_cards)} cards, pending: {len(pending)}")
    log_line(
        f"Rate limit: {REQUESTS_PER_SECOND} req/s, workers: {MAX_WORKERS}, "
        f"pool_timeout: {PER_CARD_POOL_TIMEOUT_SECONDS}s, "
        f"failed_retries: {failed_retry_rounds}"
    )

    lock = threading.Lock()
    if pending:
        run_start = time.monotonic()
        monitor = ScrapeProgressMonitor(total_pending=len(pending), output_path=output_path)
        monitor.start()

        try:
            scrapers = [create_scraper() for _ in range(MAX_WORKERS)]
            pool_items, failure_items = _scrape_pending_bounded(
                pending,
                scrapers=scrapers,
                successful_cards=successful_cards,
                rejected_cards=rejected_cards,
                output_path=output_path,
                monitor=monitor,
                checkpoint_every=checkpoint_every,
                lock=lock,
                run_start=run_start,
                round_label="primary",
            )
            retry_items = _merge_retry_items(pool_items, failure_items)

            for round_num in range(1, failed_retry_rounds + 1):
                if not retry_items:
                    break
                log_line(
                    f"[BATCH_RETRY] round {round_num}/{failed_retry_rounds}: "
                    f"{len(retry_items)} cards (fresh HTTP sessions)"
                )
                scrapers = [create_scraper() for _ in range(MAX_WORKERS)]
                retry_cards = [card for card, _ in retry_items]
                pool_items, failure_items = _scrape_pending_bounded(
                    retry_cards,
                    scrapers=scrapers,
                    successful_cards=successful_cards,
                    rejected_cards=rejected_cards,
                    output_path=output_path,
                    monitor=monitor,
                    checkpoint_every=checkpoint_every,
                    lock=lock,
                    run_start=run_start,
                    round_label=f"retry-{round_num}",
                    use_monitor=False,
                )
                retry_items = _merge_retry_items(pool_items, failure_items)
                log_line(
                    f"[BATCH_RETRY] round {round_num} done: "
                    f"{len(retry_items)} still queued for retry or reject"
                )

            if retry_items:
                log_line(
                    f"[WARN] {len(retry_items)} cards failed after all retry rounds; "
                    "marking rejected"
                )
                for card, error in retry_items:
                    _log_fail(card, error, will_retry=False)
                    _reject_card(card, error, rejected_cards)
        finally:
            monitor.stop()
            monitor.log_summary()
    else:
        log_line("Nothing pending in this batch slice.")

    with lock:
        _save_cards(output_path, successful_cards)
    _save_rejected(rejected_path, rejected_cards)

    audit_slice_completion(
        slice_cards=slice_cards,
        output_path=output_path,
        rejected_cards=rejected_cards,
        batch_index=batch_index,
        batch_count=batch_count,
    )

    log_line(
        f"Done: {len(successful_cards)} cards saved, {len(rejected_cards)} rejected"
    )
    return output_path, rejected_path, len(successful_cards), len(rejected_cards)
