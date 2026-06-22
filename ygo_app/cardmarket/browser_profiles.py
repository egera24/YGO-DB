"""Chrome profile pool for Cardmarket browser scraping (429 rotation)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ygo_app.cardmarket.paths import CARDMARKET_BROWSER_STATE_PATH, CATALOG_DIR
from ygo_app.yugipedia.scrape_progress import log_line

DEFAULT_PROFILE_NAME = "default"
LEGACY_CDP_PROFILE_DIR = CATALOG_DIR / "cardmarket_chrome_profile"
PROFILE_STATE_PATH = CATALOG_DIR / "cardmarket_profile_state.json"
_PROFILE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}$")


def profiles_root() -> Path:
    return CATALOG_DIR / "cardmarket_profiles"


@dataclass
class ProfileState:
    active: str
    pool: list[str]
    burned: list[str] = field(default_factory=list)
    burned_at: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "pool": self.pool,
            "burned": self.burned,
            "burned_at": self.burned_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProfileState:
        pool = [str(p) for p in data.get("pool") or [DEFAULT_PROFILE_NAME]]
        active = str(data.get("active") or pool[0])
        burned = [str(b) for b in data.get("burned") or []]
        burned_at = {str(k): str(v) for k, v in (data.get("burned_at") or {}).items()}
        return cls(active=active, pool=pool, burned=burned, burned_at=burned_at)


def normalize_profile_name(name: str) -> str:
    text = name.strip()
    if not text or not _PROFILE_NAME_RE.match(text):
        raise ValueError(f"Invalid browser profile name: {name!r}")
    return text


def parse_profile_pool(raw: str | None) -> list[str]:
    if not raw or not raw.strip():
        return [DEFAULT_PROFILE_NAME]
    names: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        name = normalize_profile_name(part)
        if name not in seen:
            names.append(name)
            seen.add(name)
    return names or [DEFAULT_PROFILE_NAME]


def resolve_profile_pool(
    cli_value: str | None,
    env_value: str | None,
) -> list[str]:
    if cli_value and cli_value.strip():
        return parse_profile_pool(cli_value)
    if env_value and env_value.strip():
        return parse_profile_pool(env_value)
    return [DEFAULT_PROFILE_NAME]


def profile_dir(name: str) -> Path:
    normalized = normalize_profile_name(name)
    if normalized == DEFAULT_PROFILE_NAME and LEGACY_CDP_PROFILE_DIR.is_dir():
        return LEGACY_CDP_PROFILE_DIR
    return profiles_root() / normalized


def profile_storage_path(name: str) -> Path:
    normalized = normalize_profile_name(name)
    if normalized == DEFAULT_PROFILE_NAME and CARDMARKET_BROWSER_STATE_PATH.is_file():
        if not (profiles_root() / DEFAULT_PROFILE_NAME / "browser_state.json").is_file():
            return CARDMARKET_BROWSER_STATE_PATH
    return profile_dir(normalized) / "browser_state.json"


def active_browser_storage_path() -> Path:
    """Storage path for the currently active profile in the pool."""
    state = load_profile_state()
    return profile_storage_path(state.active)


def load_profile_state(
    *,
    pool: list[str] | None = None,
    state_path: Path = PROFILE_STATE_PATH,
) -> ProfileState:
    effective_pool = pool or [DEFAULT_PROFILE_NAME]
    if state_path.is_file():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            state = ProfileState.from_dict(data)
            merged_pool = list(state.pool)
            for name in effective_pool:
                if name not in merged_pool:
                    merged_pool.append(name)
            state.pool = merged_pool
            if state.active not in state.pool:
                state.active = next(
                    (n for n in state.pool if n not in state.burned),
                    state.pool[0],
                )
            return state
        except (OSError, json.JSONDecodeError):
            pass
    active = next((n for n in effective_pool if n), DEFAULT_PROFILE_NAME)
    return ProfileState(active=active, pool=list(effective_pool))


def save_profile_state(
    state: ProfileState,
    *,
    state_path: Path = PROFILE_STATE_PATH,
) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )


def mark_burned(state: ProfileState, name: str, *, reason: str = "429") -> ProfileState:
    normalized = normalize_profile_name(name)
    if normalized not in state.burned:
        state.burned.append(normalized)
    state.burned_at[normalized] = datetime.now(timezone.utc).isoformat()
    return state


def next_available_profile(state: ProfileState) -> str | None:
    for name in state.pool:
        if name not in state.burned:
            return name
    return None


def switch_active_profile(state: ProfileState, name: str) -> ProfileState:
    normalized = normalize_profile_name(name)
    if normalized not in state.pool:
        state.pool.append(normalized)
    state.active = normalized
    idx = state.pool.index(normalized) + 1
    log_line(f"[PROFILE] using {normalized} ({idx}/{len(state.pool)} in pool)")
    return state


def burn_and_rotate(state: ProfileState, *, reason: str = "429") -> ProfileState | None:
    """Mark active profile burned and switch to next available. Returns None if pool exhausted."""
    burned_name = state.active
    mark_burned(state, burned_name, reason=reason)
    nxt = next_available_profile(state)
    if nxt is None:
        return None
    log_line(f"[PROFILE] {burned_name} burned ({reason}); switching to {nxt}")
    return switch_active_profile(state, nxt)


def log_pool_exhausted_hint(pool: list[str]) -> None:
    log_line(
        "[HINT] All browser profiles in the pool are rate-limited (HTTP 429). "
        f"Pool: {', '.join(pool)}. Wait several hours, then delete or edit "
        f"{PROFILE_STATE_PATH} (clear burned list), or add names via "
        "--browser-profiles / CARDMARKET_BROWSER_PROFILES."
    )
