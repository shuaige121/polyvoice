"""Small stderr logger used by servers and workers."""

from __future__ import annotations

import datetime as dt
import json
import sys
from typing import Any


def log(event: str, **fields: Any) -> None:
    payload = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
        "event": event,
        **fields,
    }
    print(json.dumps(payload, ensure_ascii=False, default=str), file=sys.stderr, flush=True)
