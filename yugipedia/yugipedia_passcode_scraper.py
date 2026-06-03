"""
Legacy CLI — delegates to ygo_app.yugipedia.passcodes.

Run from repo root:
  python -m ygo_app.jobs.scrape_yugipedia_catalog --passcodes-only
"""

from ygo_app.jobs.scrape_yugipedia_catalog import main

if __name__ == "__main__":
    import sys

    sys.argv = [sys.argv[0], "--passcodes-only", *sys.argv[1:]]
    raise SystemExit(main())
