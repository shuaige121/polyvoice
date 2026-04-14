"""TTS worker entrypoint."""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

from polyvoice.server.audio import pcm_to_b64

os.environ.setdefault("NUMBA_LOG_LEVEL", "WARNING")
logging.getLogger().setLevel(logging.WARNING)
# Real unbuffered stdout — flush=True alone still goes through TextIOWrapper.
# write_through=True bypasses internal buffering so JSON lines reach the
# parent process immediately, shaving tens of ms off first-chunk latency.
try:
    sys.stdout.reconfigure(write_through=True, line_buffering=True)
except (AttributeError, ValueError):
    pass

MAX_PCM_FRAME = 24_000


def _load_backend(name: str, options: dict[str, Any]):
    if name == "edge_tts":
        from polyvoice.backends.tts.edge_tts import EdgeTTSBackend

        return EdgeTTSBackend(options)
    if name == "cosyvoice3":
        from polyvoice.backends.tts.cosyvoice3 import CosyVoice3Backend

        return CosyVoice3Backend(options)
    raise ValueError(f"unknown tts backend: {name}")


def _send(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: worker_entry BACKEND OPTIONS_JSON")
    backend = _load_backend(sys.argv[1], json.loads(sys.argv[2]))
    _send({"ready": True, "sample_rate": backend.sample_rate})
    for line in sys.stdin:
        req = json.loads(line)
        request_id = req.get("id")
        op = req.get("op")
        try:
            if op == "health":
                _send({"id": request_id, "ok": True, "result": {"name": backend.name}})
            elif op == "list_voices":
                _send({"id": request_id, "ok": True, "result": {"voices": backend.list_voices()}})
            elif op == "speak":
                for chunk in backend.stream(req["text"], req["voice"], float(req.get("speed", 1.0))):
                    for offset in range(0, len(chunk), MAX_PCM_FRAME):
                        part = chunk[offset : offset + MAX_PCM_FRAME]
                        if part:
                            _send({"id": request_id, "chunk": pcm_to_b64(part)})
                _send({"id": request_id, "done": True, "sample_rate": backend.sample_rate})
            elif op == "shutdown":
                _send({"id": request_id, "ok": True, "result": {}})
                return
            else:
                raise ValueError(f"unsupported op: {op}")
        except Exception as exc:  # noqa: BLE001 - worker protocol returns errors as frames
            _send({"id": request_id, "ok": False, "error": str(exc)})


if __name__ == "__main__":
    main()
