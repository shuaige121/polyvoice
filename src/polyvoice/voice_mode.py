"""Voice mode flag controls."""

from __future__ import annotations

import argparse
from pathlib import Path

from polyvoice.config import load_config


def flag_path() -> Path:
    return load_config().voice_mode.flag_file


def is_active() -> bool:
    return flag_path().exists()


def set_active(active: bool) -> Path:
    path = flag_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if active:
        path.touch()
    else:
        path.unlink(missing_ok=True)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(prog="polyvoice")
    sub = parser.add_subparsers(dest="cmd", required=True)
    voice = sub.add_parser("voice")
    voice.add_argument("state", choices=["on", "off", "status"])
    args = parser.parse_args()
    if args.cmd == "voice":
        if args.state == "status":
            print("on" if is_active() else "off")
        else:
            path = set_active(args.state == "on")
            print(f"voice mode {args.state}: {path}")
