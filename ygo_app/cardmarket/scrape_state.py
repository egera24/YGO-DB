"""Single-file Cardmarket scrape run state (resume, dated artifacts, surrogate seq)."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from ygo_app.cardmarket.artifact_io import load_checkpoint, save_json_atomic
from ygo_app.cardmarket.paths import (
    CARDMARKET_SCRAPE_STATE_PATH,
    CATALOG_DIR,
    expansion_list_path,
    card_list_path,
)

ScrapePhase = Literal["expansion_list", "card_list", "card_details", "done"]
ScrapeMode = Literal["full", "incremental"]

STATE_VERSION = 1
RUN_DATE_RE = re.compile(r"^(\d{8})$")
EXPANSION_LIST_RE = re.compile(r"^expansion_list_(\d{8})\.json$")
CARD_LIST_RE = re.compile(r"^card_list_(\d{8})\.json$")


class ScrapeStateError(ValueError):
    """Invalid or inconsistent scrape state."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_run_date() -> str:
    return date.today().strftime("%Y%m%d")


def parse_run_date(value: str) -> str:
    text = (value or "").strip()
    if not RUN_DATE_RE.match(text):
        raise ScrapeStateError(f"Invalid run_date (expected YYYYMMDD): {value!r}")
    return text


def assign_expansion_seq(expansions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign contiguous 1-based seq in stable expansion_id order."""
    ordered = sorted(expansions, key=lambda e: int(e["expansion_id"]))
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(ordered, start=1):
        item = dict(row)
        item["seq"] = idx
        out.append(item)
    return out


def find_latest_dated_file(pattern: re.Pattern[str]) -> tuple[str, Path] | None:
    """Return (run_date, path) for the newest matching file in CATALOG_DIR."""
    best_date: str | None = None
    best_path: Path | None = None
    if not CATALOG_DIR.is_dir():
        return None
    for path in CATALOG_DIR.iterdir():
        if not path.is_file():
            continue
        match = pattern.match(path.name)
        if not match:
            continue
        run_date = match.group(1)
        if best_date is None or run_date > best_date:
            best_date = run_date
            best_path = path
    if best_date is None or best_path is None:
        return None
    return best_date, best_path


def find_latest_expansion_list() -> tuple[str, Path] | None:
    return find_latest_dated_file(EXPANSION_LIST_RE)


def find_latest_card_list() -> tuple[str, Path] | None:
    return find_latest_dated_file(CARD_LIST_RE)


def default_state(*, run_date: str | None = None, mode: ScrapeMode = "full") -> dict[str, Any]:
    rd = parse_run_date(run_date or today_run_date())
    return {
        "version": STATE_VERSION,
        "run_date": rd,
        "mode": mode,
        "last_completed_seq": 0,
        "last_completed_card_index": -1,
        "expansion_list_file": expansion_list_path(rd).name,
        "card_list_file": card_list_path(rd).name,
        "phase": "expansion_list",
        "updated_at": utc_now_iso(),
    }


def load_scrape_state(path: Path = CARDMARKET_SCRAPE_STATE_PATH) -> dict[str, Any]:
    data = load_checkpoint(path)
    if not data:
        return {}
    if int(data.get("version", 0)) != STATE_VERSION:
        raise ScrapeStateError(f"Unsupported scrape state version in {path}")
    return data


def save_scrape_state(
    state: dict[str, Any],
    path: Path = CARDMARKET_SCRAPE_STATE_PATH,
) -> None:
    payload = dict(state)
    payload["version"] = STATE_VERSION
    payload["updated_at"] = utc_now_iso()
    save_json_atomic(path, payload)


def ensure_scrape_state(
    *,
    run_date: str | None = None,
    mode: ScrapeMode = "full",
    phase: ScrapePhase = "expansion_list",
    path: Path = CARDMARKET_SCRAPE_STATE_PATH,
    reset: bool = False,
) -> dict[str, Any]:
    """Load existing state or create a new run for run_date (default today)."""
    rd = parse_run_date(run_date or today_run_date())
    if not reset and path.is_file():
        state = load_scrape_state(path)
        if state and state.get("run_date") == rd:
            return state
    state = default_state(run_date=rd, mode=mode)
    state["phase"] = phase
    save_scrape_state(state, path)
    return state


def resolve_expansion_list_file(state: dict[str, Any]) -> Path:
    name = state.get("expansion_list_file")
    if name:
        return CATALOG_DIR / str(name)
    return expansion_list_path(str(state["run_date"]))


def resolve_card_list_file(state: dict[str, Any]) -> Path:
    name = state.get("card_list_file")
    if name:
        return CATALOG_DIR / str(name)
    return card_list_path(str(state["run_date"]))


def update_state_seq(
    state: dict[str, Any],
    seq: int,
    *,
    phase: ScrapePhase | None = None,
    path: Path = CARDMARKET_SCRAPE_STATE_PATH,
) -> dict[str, Any]:
    updated = dict(state)
    updated["last_completed_seq"] = int(seq)
    if phase is not None:
        updated["phase"] = phase
    save_scrape_state(updated, path)
    return updated


def update_state_card_index(
    state: dict[str, Any],
    index: int,
    *,
    phase: ScrapePhase | None = None,
    path: Path = CARDMARKET_SCRAPE_STATE_PATH,
) -> dict[str, Any]:
    updated = dict(state)
    updated["last_completed_card_index"] = int(index)
    if phase is not None:
        updated["phase"] = phase
    save_scrape_state(updated, path)
    return updated


def next_expansion_seq(state: dict[str, Any]) -> int:
    return int(state.get("last_completed_seq", 0)) + 1


def rollback_cards_after_seq(
    cards: list[dict[str, Any]],
    last_completed_seq: int,
) -> list[dict[str, Any]]:
    cutoff = int(last_completed_seq)
    return [c for c in cards if int(c.get("expansion_seq", 0)) <= cutoff]
