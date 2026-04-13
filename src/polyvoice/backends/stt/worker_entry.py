"""STT worker entrypoint."""

from __future__ import annotations

import json
import sys
from typing import Any

from polyvoice.server.audio import b64_to_pcm


def _load_backend(name: str, options: dict[str, Any]):
    if name == "sensevoice":
        from polyvoice.backends.stt.sensevoice import SenseVoiceBackend

        return SenseVoiceBackend(options)
    if name == "faster_whisper":
        from polyvoice.backends.stt.faster_whisper import FasterWhisperBackend

        return FasterWhisperBackend(options)
    raise ValueError(f"unknown stt backend: {name}")


def _send(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: worker_entry BACKEND OPTIONS_JSON")
    backend = _load_backend(sys.argv[1], json.loads(sys.argv[2]))
    _send({"ready": True, "sample_rate": 16000})
    for line in sys.stdin:
        req = json.loads(line)
        request_id = req.get("id")
        op = req.get("op")
        try:
            if op == "health":
                _send({"id": request_id, "ok": True, "result": {"name": backend.name}})
            elif op == "transcribe":
                transcript = backend.transcribe(
                    b64_to_pcm(req["pcm_b64"]),
                    int(req.get("sr", 16000)),
                    list(req.get("hotwords", [])),
                    req.get("language"),
                )
                _send(
                    {
                        "id": request_id,
                        "ok": True,
                        "result": {
                            "text": transcript.text,
                            "language": transcript.language or req.get("language") or "auto",
                            "segments": transcript.segments or [],
                        },
                    }
                )
            elif op == "shutdown":
                _send({"id": request_id, "ok": True, "result": {}})
                return
            else:
                raise ValueError(f"unsupported op: {op}")
        except Exception as exc:  # noqa: BLE001
            _send({"id": request_id, "ok": False, "error": str(exc)})


if __name__ == "__main__":
    main()
