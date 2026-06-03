"""Scrape Yugipedia card detail pages into yugipedia_all_cards.json."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from ygo_app.yugipedia.constants import CHECKPOINT_EVERY, MAX_WORKERS, REQUESTS_PER_SECOND
from ygo_app.yugipedia.http_client import create_scraper, fetch_page
from ygo_app.yugipedia.parsing import parse_card_page
from ygo_app.yugipedia.paths import (
    ALL_CARDS_PATH,
    PASSCODE_LIST_PATH,
    REJECTED_PATH,
    ensure_catalog_dir,
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


def _process_card(scraper, input_card: dict) -> dict:
    html, error = fetch_page(scraper, input_card["url"])
    if html is None:
        return {"success": False, "input_card": input_card, "error": error}
    card_data, parse_error = parse_card_page(html, input_card)
    if parse_error:
        return {"success": False, "input_card": input_card, "error": parse_error}
    return {"success": True, "card_data": card_data, "input_card": input_card}


def scrape_card_details(
    *,
    input_path: Path | None = None,
    output_path: Path | None = None,
    rejected_path: Path | None = None,
    resume: bool = False,
    checkpoint_every: int = CHECKPOINT_EVERY,
) -> tuple[Path, Path, int, int]:
    """
    Scrape all card pages from passcode list.

    Returns (output_path, rejected_path, success_count, rejected_count).
    """
    ensure_catalog_dir()
    input_path = input_path or PASSCODE_LIST_PATH
    output_path = output_path or ALL_CARDS_PATH
    rejected_path = rejected_path or REJECTED_PATH

    if not input_path.exists():
        raise FileNotFoundError(f"Passcode list not found: {input_path}")

    input_cards = _load_json_list(input_path)
    done_passwords: set[str] = set()
    successful_cards: list[dict] = []

    if resume and output_path.exists():
        successful_cards = _load_json_list(output_path)
        done_passwords = _passwords_done(output_path)
        print(f"Resume: {len(done_passwords)} cards already scraped")

    pending = [c for c in input_cards if c["password"] not in done_passwords]
    rejected_cards: list[dict] = []
    if rejected_path.exists():
        try:
            with rejected_path.open("r", encoding="utf-8") as f:
                prev = json.load(f)
            if isinstance(prev, dict) and "rejected_cards" in prev:
                rejected_cards = list(prev["rejected_cards"])
        except (json.JSONDecodeError, OSError):
            rejected_cards = []

    print(f"Input: {len(input_cards)} cards, pending: {len(pending)}")
    print(f"Rate limit: {REQUESTS_PER_SECOND} req/s, workers: {MAX_WORKERS}")

    scrapers = [create_scraper() for _ in range(MAX_WORKERS)]
    lock = threading.Lock()
    completed = 0
    start_time = time.time()

    def maybe_checkpoint() -> None:
        with lock:
            _save_cards(output_path, successful_cards)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for idx, input_card in enumerate(pending):
            scraper = scrapers[idx % MAX_WORKERS]
            future = executor.submit(_process_card, scraper, input_card)
            futures[future] = input_card

        for future in as_completed(futures):
            result = future.result()
            completed += 1
            input_card = result["input_card"]

            with lock:
                if result["success"]:
                    successful_cards.append(result["card_data"])
                else:
                    entry = input_card.copy()
                    entry["rejection_reason"] = result.get("error", "unknown")
                    entry["rejection_timestamp"] = datetime.now().isoformat()
                    rejected_cards.append(entry)

                if completed % checkpoint_every == 0:
                    maybe_checkpoint()

            if completed % 50 == 0 or completed == len(pending):
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (len(pending) - completed) / rate if rate > 0 else 0
                status = "ok" if result["success"] else "fail"
                print(
                    f"[{completed}/{len(pending)}] {status} "
                    f"{input_card['name'][:40]:40} | {rate:.1f}/s | ETA {eta/60:.1f}m"
                )

    _save_cards(output_path, successful_cards)
    _save_rejected(rejected_path, rejected_cards)

    print(
        f"Done: {len(successful_cards)} cards saved, {len(rejected_cards)} rejected "
        f"({completed} processed this run)"
    )
    return output_path, rejected_path, len(successful_cards), len(rejected_cards)
