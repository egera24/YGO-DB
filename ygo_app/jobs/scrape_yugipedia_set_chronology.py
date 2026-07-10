"""Scrape Yugipedia Set chronology into JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ygo_app.yugipedia.http_client import create_scraper, fetch_page
from ygo_app.yugipedia.paths import SET_CHRONOLOGY_PATH, ensure_catalog_dir
from ygo_app.yugipedia.set_chronology import SET_CHRONOLOGY_URL, parse_set_chronology_html


def scrape_set_chronology(*, output_path=SET_CHRONOLOGY_PATH) -> list[dict]:
    ensure_catalog_dir()
    scraper = create_scraper()
    html, err = fetch_page(scraper, SET_CHRONOLOGY_URL)
    if err or not html:
        raise RuntimeError(f"Failed to fetch Set chronology: {err}")

    rows = parse_set_chronology_html(html)
    if not rows:
        raise RuntimeError("No TCG sets parsed from Set chronology page")

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(rows)} TCG sets to {output_path}")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Yugipedia Set chronology")
    parser.add_argument(
        "--output",
        type=str,
        default=str(SET_CHRONOLOGY_PATH),
        help="Output JSON path",
    )
    args = parser.parse_args(argv)
    output = Path(args.output)
    try:
        scrape_set_chronology(output_path=output)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
