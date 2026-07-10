"""One-off consistency check for data/catalog Cardmarket artifacts."""
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, "-m", "ygo_app.jobs.cardmarket_catalog_status", "--strict"]
    return subprocess.call(cmd, cwd=root)


if __name__ == "__main__":
  raise SystemExit(main())
