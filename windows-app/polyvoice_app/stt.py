"""SenseVoice STT integration through sherpa-onnx or a WSL HTTP route."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from polyvoice_app import paths

logger = logging.getLogger("polyvoice.stt")


class STTError(RuntimeError):
    """Base STT error."""


class STTNotReadyError(STTError):
    """Raised when the local model or recognizer dependency is unavailable."""


@dataclass(frozen=True)
class STTConfig:
    route: str = "local"
    wsl_url: str = "http://127.0.0.1:7892"
    model_dir: Path | None = None
    num_threads: int = 4


class STTEngine:
    def __init__(self, config: STTConfig | None = None) -> None:
        self.config = config or STTConfig()
        self._recognizer: Any | None = None

    @property
    def model_dir(self) -> Path:
        return self.config.model_dir or paths.default_model_dir()

    @property
    def model_path(self) -> Path:
        return self.model_dir / "model.int8.onnx"

    @property
    def tokens_path(self) -> Path:
        return self.model_dir / "tokens.txt"

    def model_ready(self) -> bool:
        return self.model_path.exists() and self.tokens_path.exists()

    def transcribe(self, pcm_bytes: bytes, sr: int = 16000) -> str:
        started = time.monotonic()
        if self.config.route == "wsl":
            text = self._transcribe_wsl(pcm_bytes, sr)
        else:
            text = self._transcribe_local(pcm_bytes, sr)
        logger.info(
            "transcribe complete",
            extra={
                "event": "transcribe_complete",
                "route": self.config.route,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return text

    def warmup(self) -> None:
        silence = b"\x00" * 16000
        try:
            self.transcribe(silence, sr=16000)
        except STTNotReadyError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("stt warmup failed", extra={"event": "stt_warmup_failed", "error": str(exc)})

    def _transcribe_local(self, pcm_bytes: bytes, sr: int) -> str:
        if not self.model_ready():
            raise STTNotReadyError(model_missing_message(self.model_dir))
        recognizer = self._load_recognizer()
        np = _numpy()
        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        stream = recognizer.create_stream()
        stream.accept_waveform(sr, samples)
        recognizer.decode_stream(stream)
        result = recognizer.get_result(stream)
        if isinstance(result, str):
            return result.strip()
        return str(getattr(result, "text", "")).strip()

    def _transcribe_wsl(self, pcm_bytes: bytes, sr: int) -> str:
        url = self.config.wsl_url.rstrip("/") + "/v1/audio/transcriptions"
        request = urllib.request.Request(
            url,
            data=pcm_bytes,
            headers={"Content-Type": "application/octet-stream", "X-Sample-Rate": str(sr)},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise STTError(f"WSL STT route failed: {exc}") from exc
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return body.strip()
        return str(payload.get("text", "")).strip()

    def _load_recognizer(self) -> Any:
        if self._recognizer is not None:
            return self._recognizer
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise STTNotReadyError("sherpa-onnx is required for local STT") from exc
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(self.model_path),
            tokens=str(self.tokens_path),
            num_threads=self.config.num_threads,
            provider="cpu",
            use_itn=True,
        )
        logger.info(
            "stt recognizer loaded",
            extra={"event": "stt_recognizer_loaded", "model": str(self.model_path)},
        )
        return self._recognizer


def model_missing_message(model_dir: Path | None = None) -> str:
    model_dir = model_dir or paths.default_model_dir()
    return (
        "SenseVoice model files are missing. Expected model.int8.onnx and tokens.txt at "
        f"{model_dir}. Run scripts/download-model.py from windows-app when it is available."
    )


def _numpy() -> Any:
    try:
        import numpy as np
    except ImportError as exc:
        raise STTNotReadyError("numpy is required for local STT") from exc
    return np
