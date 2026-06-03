"""Orchestrate Yugipedia passcode + details scrape."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ygo_app.yugipedia.details import scrape_card_details
from ygo_app.yugipedia.passcodes import run_passcode_scrape
from ygo_app.yugipedia.paths import (
    ALL_CARDS_PATH,
    PASSCODE_LIST_PATH,
    REJECTED_PATH,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Yugipedia card catalog")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full", action="store_true", help="Passcode list + card details")
    group.add_argument("--passcodes-only", action="store_true", help="Fetch passcode index only")
    group.add_argument("--details-only", action="store_true", help="Scrape card pages from passcode list")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip passwords already present in output JSON (details scrape)",
    )
    parser.add_argument("--input", type=Path, default=None, help="Passcode list path")
    parser.add_argument("--output", type=Path, default=None, help="All cards output path")
    parser.add_argument(
        "--batch-index",
        type=int,
        default=None,
        help="0-based batch index for details scrape (requires --batch-count, --details-only)",
    )
    parser.add_argument(
        "--batch-count",
        type=int,
        default=None,
        help="Total number of details batches (e.g. 6 for GHA)",
    )
    args = parser.parse_args(argv)

    input_path = args.input or PASSCODE_LIST_PATH
    output_path = args.output or ALL_CARDS_PATH

    if (args.batch_index is None) != (args.batch_count is None):
        print("Provide both --batch-index and --batch-count, or neither.", file=sys.stderr)
        return 1
    if args.batch_index is not None and not args.details_only:
        print("--batch-index/--batch-count require --details-only.", file=sys.stderr)
        return 1
    if args.batch_index is not None and (
        args.batch_index < 0 or args.batch_count < 1 or args.batch_index >= args.batch_count
    ):
        print(
            f"Invalid batch: index={args.batch_index}, count={args.batch_count}",
            file=sys.stderr,
        )
        return 1

    try:
        if args.full or args.passcodes_only:
            run_passcode_scrape(output_path=input_path)

        if args.full or args.details_only:
            if not input_path.exists():
                print("Passcode list missing. Run --passcodes-only or --full first.", file=sys.stderr)
                return 1
            scrape_card_details(
                input_path=input_path,
                output_path=output_path,
                rejected_path=REJECTED_PATH,
                resume=args.resume,
                batch_index=args.batch_index,
                batch_count=args.batch_count,
            )
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
