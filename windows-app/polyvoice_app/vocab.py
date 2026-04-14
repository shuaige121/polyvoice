"""Phase 2 vocabulary refresh stubs.

Phase 3 fills in the WSL distro probe, Claude history scan, jieba tokenization,
and master vocab merge. The Phase 2 GUI only needs a non-blocking operation
that creates the expected hotwords file and records when refresh was requested.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from polyvoice_app import paths

logger = logging.getLogger("polyvoice.vocab")


def refresh_from_wsl(distro: str | None = None) -> None:
    """Write a placeholder hotwords file with the current timestamp."""
    paths.ensure_app_dirs()
    timestamp = datetime.now(UTC).isoformat()
    lines = [
        "# polyvoice Phase 2 placeholder hotwords",
        f"# refreshed_at={timestamp}",
    ]
    if distro:
        lines.append(f"# distro={distro}")
    lines.append("")
    paths.hotwords_path().write_text("\n".join(lines), encoding="utf-8")
    logger.info(
        "vocab refresh placeholder written",
        extra={
            "event": "vocab_refresh_placeholder",
            "path": str(paths.hotwords_path()),
            "distro": distro,
            "refreshed_at": timestamp,
        },
    )
