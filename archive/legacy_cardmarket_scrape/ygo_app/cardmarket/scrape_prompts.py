"""Interactive console prompts for Cardmarket scrape jobs."""

from __future__ import annotations

import sys
import threading
from typing import Callable, Literal

from ygo_app.yugipedia.scrape_progress import log_line

NoProductRowsAction = Literal["retry", "skip", "terminate"]

_prompt_lock = threading.Lock()

PromptFn = Callable[[str, int, str], NoProductRowsAction]


def _stdin_prompt(url: str, expansion_id: int, expansion_name: str) -> NoProductRowsAction:
    log_line("[CARD_LIST] No product rows on page 1 — verify in browser before continuing")
    log_line(f"  Expansion: {expansion_id} — {expansion_name}")
    log_line(f"  URL: {url}")
    log_line(
        "Open the URL and check whether the page loaded correctly "
        "(cards listed, Cloudflare, etc.)."
    )
    log_line("  [r] Retry this page")
    log_line("  [c] Continue job (skip this expansion)")
    log_line("  [q] Terminate job")

    while True:
        try:
            choice = input("Choice: ").strip().lower()
        except EOFError:
            return "skip"
        if choice in ("r", "retry"):
            return "retry"
        if choice in ("c", "continue", "skip"):
            return "skip"
        if choice in ("q", "quit", "terminate"):
            return "terminate"
        log_line("Invalid choice — enter r, c, or q.")


def prompt_no_product_rows(
    *,
    url: str,
    expansion_id: int,
    expansion_name: str,
    enabled: bool = True,
    prompt_fn: PromptFn | None = None,
) -> NoProductRowsAction:
    """Ask the user how to proceed when page 1 has no productRow elements."""
    if prompt_fn is not None:
        with _prompt_lock:
            return prompt_fn(url, expansion_id, expansion_name)
    if not enabled or not sys.stdin.isatty():
        return "skip"
    with _prompt_lock:
        return _stdin_prompt(url, expansion_id, expansion_name)
