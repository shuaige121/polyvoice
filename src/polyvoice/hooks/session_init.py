"""Claude Code SessionStart hook for voice mode."""

from __future__ import annotations

from polyvoice.config import ROOT
from polyvoice.voice_mode import is_active


def main() -> None:
    if not is_active():
        return
    prompt = ROOT / "assets/voice_mode_prompt.md"
    print(prompt.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
