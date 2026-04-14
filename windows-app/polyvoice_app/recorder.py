"""Microphone recording via sounddevice InputStream."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("polyvoice.recorder")


class RecorderError(RuntimeError):
    """Raised when recording cannot start or stop cleanly."""


@dataclass(frozen=True)
class MicSelection:
    name: str | None = None
    index: int | None = None


class Recorder:
    def __init__(
        self,
        mic: MicSelection | None = None,
        samplerate: int = 16000,
        max_recording_s: float = 60,
    ) -> None:
        self.mic = mic or MicSelection()
        self.samplerate = samplerate
        self.max_recording_s = max_recording_s
        self._stream: Any | None = None
        self._chunks: list[Any] = []
        self._started_at = 0.0
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._stream is not None:
                raise RecorderError("recording already active")
            sd = _sounddevice()
            device = resolve_device(self.mic)
            self._chunks = []
            self._started_at = time.monotonic()
            self._stream = sd.InputStream(
                samplerate=self.samplerate,
                channels=1,
                dtype="int16",
                device=device,
                callback=self._callback,
            )
            self._stream.start()
            logger.info(
                "recording started",
                extra={"event": "recording_started", "device": device, "sr": self.samplerate},
            )

    def stop(self) -> Any:
        with self._lock:
            if self._stream is None:
                raise RecorderError("recording is not active")
            stream = self._stream
            self._stream = None
        stream.stop()
        stream.close()
        np = _numpy()
        if self._chunks:
            audio = np.concatenate(self._chunks, axis=0)
        else:
            audio = np.zeros((0, 1), dtype=np.int16)
        duration_ms = int((time.monotonic() - self._started_at) * 1000)
        logger.info(
            "recording stopped",
            extra={"event": "recording_stopped", "duration_ms": duration_ms, "samples": len(audio)},
        )
        return audio.reshape(-1)

    def stop_bytes(self) -> bytes:
        return self.stop().astype("int16", copy=False).tobytes()

    def is_expired(self) -> bool:
        return self._stream is not None and time.monotonic() - self._started_at >= self.max_recording_s

    def _callback(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        del frames, time_info
        if status:
            logger.warning("recording status", extra={"event": "recording_status", "status": str(status)})
        self._chunks.append(indata.copy())


def list_microphones() -> list[dict[str, Any]]:
    sd = _sounddevice()
    devices = sd.query_devices()
    out: list[dict[str, Any]] = []
    for index, device in enumerate(devices):
        if int(device.get("max_input_channels", 0)) > 0:
            out.append(
                {
                    "index": index,
                    "name": device.get("name", f"Device {index}"),
                    "channels": device.get("max_input_channels"),
                    "default_samplerate": device.get("default_samplerate"),
                }
            )
    logger.info("microphones listed", extra={"event": "microphones_listed", "count": len(out)})
    return out


def resolve_device(selection: MicSelection) -> str | int | None:
    sd = _sounddevice()
    devices = sd.query_devices()
    if selection.name:
        for index, device in enumerate(devices):
            if device.get("name") == selection.name and int(device.get("max_input_channels", 0)) > 0:
                return index
    if selection.index is not None:
        try:
            device = devices[int(selection.index)]
        except (IndexError, TypeError):
            logger.warning(
                "stored microphone index invalid",
                extra={"event": "microphone_index_invalid", "index": selection.index},
            )
        else:
            if int(device.get("max_input_channels", 0)) > 0:
                return int(selection.index)
    return None


def _sounddevice() -> Any:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RecorderError("sounddevice is required for microphone recording") from exc
    return sd


def _numpy() -> Any:
    try:
        import numpy as np
    except ImportError as exc:
        raise RecorderError("numpy is required for microphone recording") from exc
    return np
