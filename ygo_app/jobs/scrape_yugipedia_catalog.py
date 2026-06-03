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
    args = parser.parse_args(argv)

    input_path = args.input or PASSCODE_LIST_PATH
    output_path = args.output or ALL_CARDS_PATH

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
