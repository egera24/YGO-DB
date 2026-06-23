"""Job 3: scrape Cardmarket product detail pages for prices."""

from __future__ import annotations

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from ygo_app.cardmarket.artifact_io import (
    clear_checkpoint,
    load_checkpoint,
    load_json_list,
    save_checkpoint,
    save_json,
)
from ygo_app.cardmarket.constants import (
    DEFAULT_REQUESTS_PER_SECOND,
    FetchBackend,
    INTER_EXPANSION_DELAY_BROWSER,
    RANDOM_JITTER,
    RECOVERY_REQUESTS_PER_SECOND,
)
from ygo_app.cardmarket.http_client import (
    AdaptiveRateLimiter,
    RateLimitAbort,
    create_session_pool,
    fetch_url,
    sleep_inter_page_delay,
)
from ygo_app.cardmarket.parsing import extract_full_price_data
from ygo_app.cardmarket.paths import (
    CARDMARKET_CARD_DETAILS_CHECKPOINT_PATH,
    CARDMARKET_CARD_DETAILS_PATH,
    CARDMARKET_CARD_DETAILS_REJECTION_PATH,
    CARDMARKET_CARD_LIST_PATH,
)
from ygo_app.cardmarket.scrape_session import ScrapeSession
from ygo_app.yugipedia.scrape_progress import log_line

PHASE1_MAX_RETRIES = 3
PHASE1_CHUNK_SIZE = 300
PHASE2_MAX_RETRIES = 5
PHASE2_RETRY_DELAYS = [15, 30, 45, 60, 90]
SAVE_INTERVAL = 100
DISPLAY_INTERVAL = 100

_file_lock = threading.Lock()

REQUIRED_CARD_FIELDS = (
    "expansion_id",
    "expansion_name",
    "expansion_code",
    "card_id",
    "card_name",
    "card_number",
    "card_rarity",
    "card_url",
)


def validate_input_card(card: dict[str, Any]) -> tuple[bool, str | None]:
    for field in REQUIRED_CARD_FIELDS:
        if field not in card:
            return False, f"Missing: {field}"
    if not str(card.get("expansion_code", "")).strip():
        return False, "Empty expansion_code"
    if not str(card.get("card_number", "")).strip():
        return False, "Empty card_number"
    if not str(card.get("card_url", "")).startswith("https://"):
        return False, "Invalid URL"
    return True, None


def find_duplicate_card_ids(cards: list[dict[str, Any]]) -> list[int]:
    seen: set[int] = set()
    duplicates: list[int] = []
    for card in cards:
        cid = card.get("card_id")
        if cid is None:
            continue
        cid_int = int(cid)
        if cid_int in seen and cid_int not in duplicates:
            duplicates.append(cid_int)
        seen.add(cid_int)
    return duplicates


def _process_card(
    card: dict[str, Any],
    *,
    backend: FetchBackend,
    rate_limiter: AdaptiveRateLimiter,
    session_pool,
    worker_id: int,
    max_retries: int,
) -> dict[str, Any]:
    is_valid, validation_error = validate_input_card(card)
    if not is_valid:
        return {
            "status": "rejected",
            "rejection": {
                "rejection_reason": "Failed - missing input data",
                "error_detail": validation_error,
                "card": card,
            },
        }

    scraper = None
    if session_pool is not None:
        scraper, _ = session_pool.get_session(worker_id)

    html, error = fetch_url(
        scraper,
        card["card_url"],
        backend=backend,
        rate_limiter=rate_limiter,
        jitter=RANDOM_JITTER,
        session_pool=session_pool,
        worker_id=worker_id,
        retries=max_retries,
    )
    sleep_inter_page_delay(backend)

    if not html:
        return {
            "status": "rejected",
            "rejection": {
                "rejection_reason": "Failed - site unreachable",
                "error_detail": error,
                "card": card,
            },
        }

    prices, has_na = extract_full_price_data(html)
    if has_na:
        return {
            "status": "rejected",
            "rejection": {
                "rejection_reason": "Failed - N/A",
                "error_detail": "One or more price fields are N/A",
                "card": card,
            },
        }
    if prices is None:
        return {
            "status": "rejected",
            "rejection": {
                "rejection_reason": "Failed - missing data",
                "error_detail": "Price fields missing or invalid",
                "card": card,
            },
        }

    exp_code = str(card["expansion_code"]).strip()
    card_num = str(card["card_number"]).strip()
    return {
        "status": "success",
        "data": {
            "card_data": {
                "card_id": card["card_id"],
                "card_name": card["card_name"],
                "card_rarity": card["card_rarity"],
                "card_number": card["card_number"],
                "card_set_number": f"{exp_code}-EN{card_num}",
            },
            "expansion_data": {
                "expansion_id": card["expansion_id"],
                "expansion_name": card["expansion_name"],
                "expansion_code": card["expansion_code"],
            },
            "price_data": {
                "url": card["card_url"],
                "low_price": prices["low_price"],
                "trend_price": prices["trend_price"],
                "avg_30_price": prices["avg_30_price"],
                "avg_7_price": prices["avg_7_price"],
                "avg_1_price": prices["avg_1_price"],
                "price_date": datetime.utcnow().strftime("%Y-%m-%d"),
                "currency": "EUR",
            },
        },
    }


def _save_details(
    successful: list[dict],
    rejections: list[dict],
    *,
    details_path: Path,
    rejection_path: Path,
    checkpoint: dict[str, Any] | None = None,
    checkpoint_path: Path | None = None,
) -> None:
    with _file_lock:
        save_json(details_path, successful)
        if rejections:
            save_json(rejection_path, rejections)
        if checkpoint is not None and checkpoint_path is not None:
            save_checkpoint(checkpoint_path, checkpoint)


def run_card_details_scrape(
    *,
    input_path: Path = CARDMARKET_CARD_LIST_PATH,
    output_path: Path = CARDMARKET_CARD_DETAILS_PATH,
    rejection_path: Path = CARDMARKET_CARD_DETAILS_REJECTION_PATH,
    checkpoint_path: Path = CARDMARKET_CARD_DETAILS_CHECKPOINT_PATH,
    session: ScrapeSession,
    resume: bool = False,
    limit: int | None = None,
    fast: bool = False,
    accept_rate_limit_risk: bool = False,
) -> dict[str, int]:
    cards = load_json_list(input_path)
    if limit is not None:
        cards = cards[:limit]

    duplicates = find_duplicate_card_ids(cards)
    if duplicates:
        raise ValueError(f"Duplicate card_id values in input: {duplicates[:20]}")

    backend = session.backend
    workers = session.workers
    price_rps = session.price_rps or DEFAULT_REQUESTS_PER_SECOND
    if fast:
        if not accept_rate_limit_risk:
            raise ValueError("--fast requires --i-accept-rate-limit-risk")
        workers = 20
        price_rps = 8.0
        log_line("[WARN] --fast preset: 20 workers / 8 rps (higher rate-limit risk)")

    successful: list[dict] = []
    rejections: list[dict] = []
    start_idx = 0

    if resume and checkpoint_path.is_file():
        checkpoint = load_checkpoint(checkpoint_path)
        start_idx = checkpoint.get("last_processed_index", -1) + 1
        if output_path.is_file():
            successful = load_json_list(output_path)
        if rejection_path.is_file():
            rejections = load_json_list(rejection_path)
        log_line(f"[DETAILS] resuming from card index {start_idx}")

    cards_to_process = [(start_idx + i, card) for i, card in enumerate(cards[start_idx:])]
    if not cards_to_process:
        log_line("[DETAILS] nothing to do")
        return {"success": len(successful), "rejected": len(rejections)}

    rate_limiter = AdaptiveRateLimiter(price_rps)
    session_pool = create_session_pool(backend, workers)
    stats = {
        "success": 0,
        "rejected_unreachable": 0,
        "rejected_missing_data": 0,
        "rejected_na": 0,
        "rejected_input": 0,
    }
    total_completed = 0
    last_saved_idx = start_idx - 1
    start_time = datetime.now()

    log_line(
        f"[DETAILS] phase1 workers={workers} rps={price_rps} cards={len(cards_to_process)}"
    )

    interrupted = False
    try:
        for chunk_start in range(0, len(cards_to_process), PHASE1_CHUNK_SIZE):
            chunk = cards_to_process[chunk_start : chunk_start + PHASE1_CHUNK_SIZE]
            with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
                futures = {}
                for idx_in_chunk, (abs_idx, card) in enumerate(chunk):
                    worker_id = idx_in_chunk % max(workers, 1)
                    future = executor.submit(
                        _process_card,
                        card,
                        backend=backend,
                        rate_limiter=rate_limiter,
                        session_pool=session_pool,
                        worker_id=worker_id,
                        max_retries=PHASE1_MAX_RETRIES,
                    )
                    futures[future] = abs_idx

                for future in as_completed(futures):
                    abs_idx = futures[future]
                    try:
                        result = future.result()
                    except RateLimitAbort as exc:
                        _save_details(
                            successful,
                            rejections,
                            details_path=output_path,
                            rejection_path=rejection_path,
                            checkpoint={"last_processed_index": abs_idx - 1, "phase1_complete": False},
                            checkpoint_path=checkpoint_path,
                        )
                        raise SystemExit(2) from exc

                    if result["status"] == "success":
                        successful.append(result["data"])
                        stats["success"] += 1
                    else:
                        rejections.append(result["rejection"])
                        reason = result["rejection"]["rejection_reason"]
                        if "unreachable" in reason:
                            stats["rejected_unreachable"] += 1
                        elif "missing data" in reason:
                            stats["rejected_missing_data"] += 1
                        elif "N/A" in reason:
                            stats["rejected_na"] += 1
                        elif "missing input" in reason:
                            stats["rejected_input"] += 1

                    total_completed += 1
                    last_saved_idx = abs_idx

                    if total_completed % DISPLAY_INTERVAL == 0:
                        log_line(
                            f"[DETAILS] progress {total_completed}/{len(cards_to_process)} "
                            f"success={stats['success']} rejected={len(rejections)}"
                        )

                    if total_completed % SAVE_INTERVAL == 0:
                        _save_details(
                            successful,
                            rejections,
                            details_path=output_path,
                            rejection_path=rejection_path,
                            checkpoint={"last_processed_index": abs_idx, "phase1_complete": False},
                            checkpoint_path=checkpoint_path,
                        )

                    if backend == "playwright":
                        time.sleep(random.uniform(*INTER_EXPANSION_DELAY_BROWSER))

            _save_details(
                successful,
                rejections,
                details_path=output_path,
                rejection_path=rejection_path,
                checkpoint={"last_processed_index": last_saved_idx, "phase1_complete": False},
                checkpoint_path=checkpoint_path,
            )
    except KeyboardInterrupt:
        interrupted = True
        log_line("[DETAILS] interrupted — progress saved")

    if interrupted:
        return {"success": len(successful), "rejected": len(rejections), "interrupted": 1}

    clear_checkpoint(checkpoint_path)

    # Phase 2: recover unreachable only
    recoverable = [r for r in rejections if "unreachable" in r.get("rejection_reason", "")]
    non_recoverable = [r for r in rejections if "unreachable" not in r.get("rejection_reason", "")]

    if recoverable:
        log_line(f"[DETAILS] phase2 recovery for {len(recoverable)} unreachable cards")
        recovery_limiter = AdaptiveRateLimiter(RECOVERY_REQUESTS_PER_SECOND)
        still_rejected: list[dict] = []
        recovered = 0

        for idx, rejection in enumerate(recoverable):
            card = rejection["card"]
            result = _process_card(
                card,
                backend=backend,
                rate_limiter=recovery_limiter,
                session_pool=None,
                worker_id=0,
                max_retries=PHASE2_MAX_RETRIES,
            )
            if result["status"] == "success":
                successful.append(result["data"])
                recovered += 1
                stats["success"] += 1
                stats["rejected_unreachable"] -= 1
            else:
                still_rejected.append(result["rejection"])

            if (idx + 1) % 10 == 0:
                _save_details(
                    successful,
                    non_recoverable + still_rejected,
                    details_path=output_path,
                    rejection_path=rejection_path,
                )

        rejections = non_recoverable + still_rejected
        log_line(f"[DETAILS] phase2 recovered={recovered}")

    _save_details(
        successful,
        rejections,
        details_path=output_path,
        rejection_path=rejection_path,
    )

    elapsed = (datetime.now() - start_time).total_seconds()
    log_line(
        f"[DETAILS] success={len(successful)} rejected={len(rejections)} elapsed={elapsed:.0f}s"
    )
    return {
        "success": len(successful),
        "rejected": len(rejections),
        **stats,
    }
