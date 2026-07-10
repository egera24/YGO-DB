"""CLI wrapper for normalize_rarity_codes job."""

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, "-m", "ygo_app.jobs.normalize_rarity_codes", *sys.argv[1:]]
    return subprocess.call(cmd, cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())
