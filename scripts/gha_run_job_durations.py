"""Print per-job durations for a GitHub Actions workflow run (JSON from gh run view)."""

from __future__ import annotations

import json
import sys
from datetime import datetime


def main() -> int:
    data = json.load(sys.stdin)
    jobs = data.get("jobs", [])
    for j in sorted(jobs, key=lambda x: x.get("startedAt") or ""):
        s = j.get("startedAt") or ""
        c = j.get("completedAt") or ""
        dur = ""
        if s and c:
            t0 = datetime.fromisoformat(s.replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(c.replace("Z", "+00:00"))
            dur = f"{(t1 - t0).total_seconds() / 60:.1f}m"
        print(f"{j.get('name', '?'):<22}\t{j.get('conclusion', ''):<10}\t{dur}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
