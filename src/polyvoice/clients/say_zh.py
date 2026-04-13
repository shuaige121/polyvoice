"""Command-line TTS client."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

import httpx


DEFAULT_URL = "http://127.0.0.1:7891"


def _read_text(arg: str | None) -> str:
    if arg:
        return arg
    return sys.stdin.read()


def main() -> None:
    parser = argparse.ArgumentParser(prog="say-zh")
    parser.add_argument("text", nargs="?")
    parser.add_argument("--voice", default="f1")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--backend")
    parser.add_argument("--url", default=os.environ.get("POLYVOICE_URL", DEFAULT_URL))
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.list:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{args.url}/v1/audio/voices")
            response.raise_for_status()
            for voice in response.json()["voices"]:
                print(voice)
        return

    text = _read_text(args.text).strip()
    if not text:
        raise SystemExit("text is required")

    with httpx.Client(timeout=None) as client:
        if args.backend:
            print(f"Switching backend to {args.backend}; cold start may take 10s+.", file=sys.stderr)
            response = client.post(f"{args.url}/admin/switch", json={"backend": args.backend}, timeout=180.0)
            response.raise_for_status()
        with client.stream(
            "POST",
            f"{args.url}/v1/audio/speech",
            json={
                "model": "polyvoice",
                "input": text,
                "voice": args.voice,
                "response_format": "wav",
                "speed": args.speed,
            },
        ) as response:
            response.raise_for_status()
            ffplay = subprocess.Popen(
                ["ffplay", "-loglevel", "quiet", "-nodisp", "-autoexit", "-i", "-"],
                stdin=subprocess.PIPE,
            )
            assert ffplay.stdin is not None
            for chunk in response.iter_bytes():
                ffplay.stdin.write(chunk)
                ffplay.stdin.flush()
            ffplay.stdin.close()
            ffplay.wait()
