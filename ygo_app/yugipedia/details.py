"""Scrape Yugipedia card detail pages into yugipedia_all_cards.json."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path

from ygo_app.yugipedia.constants import (
    BATCH_POOL_TIMEOUT_SECONDS,
    BATCH_WORKERS,
    CHECKPOINT_EVERY,
    FAILED_RETRY_ROUNDS,
    PARSE_BATCH_SIZE,
    PROGRESS_LOG_EVERY,
    REQUESTS_PER_SECOND,
)
from ygo_app.yugipedia.http_client import (
    create_session,
    fetch_current_revisions,
    fetch_page,
    fetch_pages_batch,
    normalize_wiki_title,
    wiki_title_from_url,
)
from ygo_app.yugipedia.passcodes import limit_passcode_list
from ygo_app.yugipedia.parsing import parse_card_page
from ygo_app.yugipedia.paths import (
    ALL_CARDS_PATH,
    PASSCODE_LIST_PATH,
    REJECTED_PATH,
    SET_CHRONOLOGY_PATH,
    ensure_catalog_dir,
)
from ygo_app.yugipedia.scrape_progress import (
    BatchIncompleteError,
    ScrapeProgressMonitor,
    is_retryable_error,
    log_line,
)
from ygo_app.yugipedia.supplements import (
    apply_supplements_to_card,
    load_set_release_lookup,
    supplements_complete,
)


def _load_json_list(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def input_card_key(card: dict) -> str:
    """Stable dedup/checkpoint key for a passcode-list entry."""
    pw = str(card.get("password") or "").strip()
    if pw:
        return pw.zfill(8)
    return card.get("url") or ""


def saved_card_key(card: dict) -> str:
    """Matching key for an already-scraped card (id/passcode or source_url)."""
    pid = card.get("id")
    if pid not in (None, ""):
        return str(pid).zfill(8)
    return card.get("source_url") or ""


def _index_cards_by_key(cards: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for card in cards:
        key = saved_card_key(card)
        if key:
            out[key] = card
    return out


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
    slice_passwords = {input_card_key(c) for c in slice_cards}
    saved: set[str] = set()
    if output_path.exists():
        for c in _load_json_list(output_path):
            key = saved_card_key(c)
            if key:
                saved.add(key)
    rejected_pw = {input_card_key(c) for c in rejected_cards if input_card_key(c)}
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


def _card_title(card: dict) -> str | None:
    return wiki_title_from_url(card.get("url") or "")


def _title_key(card: dict) -> str | None:
    title = _card_title(card)
    return normalize_wiki_title(title) if title else None


def _apply_page_meta(card_data: dict, *, revid: int | None, touched: str | None) -> None:
    if revid is not None:
        card_data["page_revid"] = revid
    if touched:
        card_data["page_touched"] = touched


def _revision_unchanged(
    existing: dict,
    current: dict[str, int | str | None] | None,
) -> bool:
    if current is None:
        return False
    stored = existing.get("page_revid")
    current_revid = current.get("revid")
    if stored is None or current_revid is None:
        return False
    return int(stored) == int(current_revid)


def _filter_pending_with_revisions(
    slice_cards: list[dict],
    *,
    existing_by_key: dict[str, dict],
    resume: bool,
    session,
) -> tuple[list[dict], int]:
    """Return cards needing fetch and count of revision-skipped cards."""
    if not resume:
        return list(slice_cards), 0

    titles = [_card_title(c) for c in slice_cards]
    titles = [t for t in titles if t]
    current_revisions = fetch_current_revisions(session, titles) if titles else {}

    pending: list[dict] = []
    skipped = 0
    for card in slice_cards:
        key = input_card_key(card)
        existing = existing_by_key.get(key)
        if existing is None:
            pending.append(card)
            continue
        if not supplements_complete(existing):
            pending.append(card)
            continue
        if existing.get("page_revid") is None:
            pending.append(card)
            continue
        title = _card_title(card)
        norm = normalize_wiki_title(title) if title else None
        current = None
        if title and title in current_revisions:
            current = current_revisions[title]
        elif norm:
            for api_title, meta in current_revisions.items():
                if normalize_wiki_title(api_title) == norm:
                    current = meta
                    break
        if _revision_unchanged(existing, current):
            skipped += 1
            continue
        pending.append(card)

    if skipped:
        log_line(f"[REV_SKIP] unchanged pages skipped={skipped}")
    return pending, skipped


def _process_parsed_card(
    session,
    input_card: dict,
    card_data: dict,
    *,
    set_release_lookup: dict[str, str],
    scrape_supplements: bool,
) -> dict:
    if not card_data.get("card_sets"):
        return {
            "success": False,
            "input_card": input_card,
            "error": "No English (TCG) printings",
        }

    if scrape_supplements:
        supplement_base = {**card_data}
        sup_update, sup_error = apply_supplements_to_card(
            session,
            supplement_base,
            set_release_lookup=set_release_lookup,
        )
        if sup_error:
            return {"success": False, "input_card": input_card, "error": sup_error}
        card_data = {**card_data, **sup_update}

    return {"success": True, "card_data": card_data, "input_card": input_card}


def _fetch_html_for_card(
    session,
    input_card: dict,
    batch_results: dict,
) -> tuple[str | None, int | None, str | None, str | None]:
    """Return html, revid, touched, error for one card (batch result or fallback)."""
    title = _card_title(input_card)
    if not title:
        return None, None, None, "InvalidWikiUrl"

    norm = normalize_wiki_title(title)
    fetch = None
    for api_title, result in batch_results.items():
        if normalize_wiki_title(api_title) == norm:
            fetch = result
            break
    if fetch is None:
        for api_title, result in batch_results.items():
            if api_title == title:
                fetch = result
                break

    if fetch is not None and fetch.html:
        return fetch.html, fetch.revid, fetch.touched, None

    if fetch is not None and fetch.error == "MissingPage":
        return None, None, None, "MissingPage"

    html, error = fetch_page(session, input_card["url"])
    if html:
        return html, None, None, None
    err = fetch.error if fetch and fetch.error else error
    return None, None, None, err or "ParseApiError: fetch failed"


def _process_card_batch(
    session,
    input_cards: list[dict],
    *,
    set_release_lookup: dict[str, str],
    scrape_supplements: bool,
) -> list[dict]:
    title_to_card: dict[str, dict] = {}
    titles: list[str] = []
    results: list[dict] = []

    for card in input_cards:
        title = _card_title(card)
        if not title:
            results.append(
                {"success": False, "input_card": card, "error": "InvalidWikiUrl"}
            )
            continue
        title_to_card[title] = card
        titles.append(title)

    batch_results = fetch_pages_batch(session, titles) if titles else {}

    for title, card in title_to_card.items():
        html, revid, touched, error = _fetch_html_for_card(session, card, batch_results)
        if html is None:
            results.append(
                {"success": False, "input_card": card, "error": error or "ParseApiError"}
            )
            continue

        card_data, parse_error = parse_card_page(html, card)
        if parse_error:
            results.append(
                {"success": False, "input_card": card, "error": parse_error}
            )
            continue

        _apply_page_meta(card_data, revid=revid, touched=touched)
        results.append(
            _process_parsed_card(
                session,
                card,
                card_data,
                set_release_lookup=set_release_lookup,
                scrape_supplements=scrape_supplements,
            )
        )
    return results


def _chunk_cards(cards: list[dict], size: int) -> list[list[dict]]:
    return [cards[i : i + size] for i in range(0, len(cards), size)]


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


def _upsert_successful_card(
    card_data: dict,
    *,
    successful_cards: list[dict],
    existing_by_key: dict[str, dict],
) -> None:
    key = saved_card_key(card_data)
    if key and key in existing_by_key:
        idx = successful_cards.index(existing_by_key[key])
        successful_cards[idx] = card_data
        existing_by_key[key] = card_data
    else:
        successful_cards.append(card_data)
        if key:
            existing_by_key[key] = card_data


def _handle_scrape_result(
    result: dict,
    *,
    successful_cards: list[dict],
    existing_by_key: dict[str, dict],
    rejected_cards: list[dict],
    retryable_failures: list[tuple[dict, str]],
) -> bool:
    input_card = result["input_card"]
    if result["success"]:
        _upsert_successful_card(
            result["card_data"],
            successful_cards=successful_cards,
            existing_by_key=existing_by_key,
        )
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
    sessions: list,
    successful_cards: list[dict],
    existing_by_key: dict[str, dict],
    rejected_cards: list[dict],
    output_path: Path,
    monitor: ScrapeProgressMonitor,
    checkpoint_every: int,
    lock: threading.Lock,
    run_start: float,
    round_label: str,
    set_release_lookup: dict[str, str],
    scrape_supplements: bool,
    use_monitor: bool = True,
) -> tuple[list[tuple[dict, str]], list[tuple[dict, str]]]:
    if not pending:
        return [], []

    batches = _chunk_cards(pending, PARSE_BATCH_SIZE)
    pool_timeout_items: list[tuple[dict, str]] = []
    retryable_failures: list[tuple[dict, str]] = []
    pool_msg = f"PoolTimeout: no completion within {BATCH_POOL_TIMEOUT_SECONDS}s"
    work_index = 0

    def maybe_checkpoint(completed: int) -> None:
        if completed > 0 and completed % checkpoint_every == 0:
            with lock:
                _save_cards(output_path, successful_cards)

    with ThreadPoolExecutor(max_workers=BATCH_WORKERS) as executor:
        in_flight: dict[Future, list[dict]] = {}

        def submit_next() -> None:
            nonlocal work_index
            while work_index < len(batches) and len(in_flight) < BATCH_WORKERS:
                batch = batches[work_index]
                session = sessions[work_index % len(sessions)]
                fut = executor.submit(
                    _process_card_batch,
                    session,
                    batch,
                    set_release_lookup=set_release_lookup,
                    scrape_supplements=scrape_supplements,
                )
                in_flight[fut] = batch
                work_index += 1

        submit_next()

        while in_flight:
            if use_monitor:
                monitor.check_abort()
            done, _ = wait(
                in_flight,
                return_when=FIRST_COMPLETED,
                timeout=BATCH_POOL_TIMEOUT_SECONDS,
            )

            if not done:
                log_line(
                    f"[WARN] Pool idle {BATCH_POOL_TIMEOUT_SECONDS}s with "
                    f"{len(in_flight)} in-flight ({round_label}); re-queueing for retry"
                )
                for batch in in_flight.values():
                    for card in batch:
                        pool_timeout_items.append((card, pool_msg))
                if work_index < len(batches):
                    for batch in batches[work_index:]:
                        for card in batch:
                            pool_timeout_items.append((card, pool_msg))
                    work_index = len(batches)
                for fut in in_flight:
                    fut.cancel()
                in_flight.clear()
                break

            for fut in done:
                batch = in_flight.pop(fut)
                try:
                    batch_results = fut.result(timeout=1)
                except Exception as exc:
                    err = f"WorkerError: {type(exc).__name__}: {exc!s}"[:120]
                    batch_results = [
                        {"success": False, "input_card": card, "error": err}
                        for card in batch
                    ]

                for result in batch_results:
                    card = result["input_card"]
                    success = False
                    with lock:
                        success = _handle_scrape_result(
                            result,
                            successful_cards=successful_cards,
                            existing_by_key=existing_by_key,
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
        by_password[input_card_key(card)] = (card, error)
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
    scrape_supplements: bool = True,
    set_chronology_path: Path = SET_CHRONOLOGY_PATH,
) -> tuple[Path, Path, int, int]:
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

    successful_cards: list[dict] = []
    existing_by_key: dict[str, dict] = {}

    if resume and output_path.exists():
        successful_cards = _load_json_list(output_path)
        existing_by_key = _index_cards_by_key(successful_cards)
        log_line(f"Resume: {len(existing_by_key)} cards already scraped")

    rejected_cards: list[dict] = []
    if rejected_path.exists():
        try:
            with rejected_path.open("r", encoding="utf-8") as f:
                prev = json.load(f)
            if isinstance(prev, dict) and "rejected_cards" in prev:
                rejected_cards = list(prev["rejected_cards"])
        except (json.JSONDecodeError, OSError):
            rejected_cards = []

    set_release_lookup: dict[str, str] = {}
    if scrape_supplements:
        if set_chronology_path.exists():
            set_release_lookup = load_set_release_lookup(set_chronology_path)
        else:
            log_line(
                f"[WARN] Set chronology missing ({set_chronology_path}); "
                "errata date enrichment disabled"
            )

    revision_session = create_session()
    pending, rev_skipped = _filter_pending_with_revisions(
        slice_cards,
        existing_by_key=existing_by_key,
        resume=resume,
        session=revision_session,
    )

    log_line(f"Input: {len(slice_cards)} cards, pending: {len(pending)}")
    log_line(
        f"Rate limit: {REQUESTS_PER_SECOND} req/s, batch_workers: {BATCH_WORKERS}, "
        f"parse_batch: {PARSE_BATCH_SIZE}, pool_timeout: {BATCH_POOL_TIMEOUT_SECONDS}s, "
        f"failed_retries: {failed_retry_rounds}, supplements: {scrape_supplements}"
    )

    lock = threading.Lock()
    if pending:
        run_start = time.monotonic()
        monitor = ScrapeProgressMonitor(total_pending=len(pending), output_path=output_path)
        monitor.start()

        try:
            sessions = [create_session() for _ in range(BATCH_WORKERS)]
            pool_items, failure_items = _scrape_pending_bounded(
                pending,
                sessions=sessions,
                successful_cards=successful_cards,
                existing_by_key=existing_by_key,
                rejected_cards=rejected_cards,
                output_path=output_path,
                monitor=monitor,
                checkpoint_every=checkpoint_every,
                lock=lock,
                run_start=run_start,
                round_label="primary",
                set_release_lookup=set_release_lookup,
                scrape_supplements=scrape_supplements,
            )
            retry_items = _merge_retry_items(pool_items, failure_items)

            for round_num in range(1, failed_retry_rounds + 1):
                if not retry_items:
                    break
                log_line(
                    f"[BATCH_RETRY] round {round_num}/{failed_retry_rounds}: "
                    f"{len(retry_items)} cards (fresh HTTP sessions)"
                )
                sessions = [create_session() for _ in range(BATCH_WORKERS)]
                retry_cards = [card for card, _ in retry_items]
                pool_items, failure_items = _scrape_pending_bounded(
                    retry_cards,
                    sessions=sessions,
                    successful_cards=successful_cards,
                    existing_by_key=existing_by_key,
                    rejected_cards=rejected_cards,
                    output_path=output_path,
                    monitor=monitor,
                    checkpoint_every=checkpoint_every,
                    lock=lock,
                    run_start=run_start,
                    round_label=f"retry-{round_num}",
                    set_release_lookup=set_release_lookup,
                    scrape_supplements=scrape_supplements,
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
        if rev_skipped:
            log_line(f"Nothing pending in this batch slice ({rev_skipped} unchanged).")
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
