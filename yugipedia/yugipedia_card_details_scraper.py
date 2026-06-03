"""
Legacy CLI — delegates to ygo_app.yugipedia.details.

Run from repo root:
  python -m ygo_app.jobs.scrape_yugipedia_catalog --details-only
"""

from ygo_app.jobs.scrape_yugipedia_catalog import main

if __name__ == "__main__":
    import sys

    sys.argv = [sys.argv[0], "--details-only", *sys.argv[1:]]
    raise SystemExit(main())
