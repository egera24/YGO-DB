"""Temporary agent debug logging. Remove after fix verified."""

from __future__ import annotations

import json
import time
from pathlib import Path

_LOG = Path("debug-552341.log")
_SESSION = "552341"


def agent_debug_log(
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict,
    *,
    run_id: str = "post-fix-2",
) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": _SESSION,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
            "runId": run_id,
        }
        with _LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion
