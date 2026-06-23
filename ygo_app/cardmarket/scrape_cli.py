"""Shared CLI arguments for Cardmarket scrape jobs."""

from __future__ import annotations

import argparse
from pathlib import Path

from ygo_app.cardmarket.constants import (
    BROWSER_DEFAULT_REQUESTS_PER_SECOND,
    BROWSER_DISCOVERY_REQUESTS_PER_SECOND,
    DEFAULT_WORKERS,
    FetchBackend,
)
from ygo_app.cardmarket.http_client import default_fetch_backend


def add_http_scrape_args(parser: argparse.ArgumentParser) -> None:
    default_backend = default_fetch_backend()
    parser.add_argument(
        "--backend",
        choices=["cloudscraper", "curl_cffi", "playwright"],
        default=None,
        help=f"HTTP backend (default: {default_backend})",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Shortcut for --backend playwright",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Visible browser (playwright only)",
    )
    parser.add_argument(
        "--polite",
        action="store_true",
        help="Recommended Cardmarket preset: --browser, workers=1, conservative RPS",
    )
    parser.add_argument(
        "--cf-login",
        action="store_true",
        help="Open Google Chrome, pass Cloudflare manually, save cookies, then exit",
    )
    parser.add_argument(
        "--browser-channel",
        choices=["chrome", "msedge", "chromium"],
        default=None,
        help="Browser for --cf-login / --headed (default: chrome)",
    )
    parser.add_argument(
        "--browser-profiles",
        default=None,
        help="Comma-separated Chrome profile pool for --browser/--headed (e.g. default,alt1,alt2)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=f"Parallel workers (default: {DEFAULT_WORKERS}, or CARDMARKET_WORKERS env)",
    )
    parser.add_argument("--rps", type=float, default=None, help="Override requests per second")
    parser.add_argument(
        "--discovery-rps",
        type=float,
        default=None,
        help="Override discovery-phase requests per second",
    )
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Incremental update (new expansions only; orchestrator recommended)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Cap items processed (testing)")


def apply_polite_args(args: argparse.Namespace) -> None:
    """Apply --polite preset after argparse (browser, 1 worker, conservative RPS)."""
    if not getattr(args, "polite", False):
        return
    args.browser = True
    args.workers = 1
    if args.rps is None:
        args.rps = BROWSER_DEFAULT_REQUESTS_PER_SECOND
    if args.discovery_rps is None:
        args.discovery_rps = BROWSER_DISCOVERY_REQUESTS_PER_SECOND


def resolve_backend_from_args(args: argparse.Namespace) -> FetchBackend | None:
    backend: FetchBackend | None = args.backend
    if args.browser:
        backend = "playwright"
    return backend


def validate_headed_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.headed and not (args.browser or args.backend == "playwright"):
        parser.error("--headed requires --browser or --backend playwright")
    if getattr(args, "incremental", False) and getattr(args, "resume", False):
        parser.error("--incremental and --resume are mutually exclusive")
