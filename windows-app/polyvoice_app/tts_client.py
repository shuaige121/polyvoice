"""Streaming TTS HTTP client with direct sounddevice playback."""

from __future__ import annotations

import json
import logging
import struct
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import BinaryIO

import numpy as np

try:
    import sounddevice as sd
except OSError as exc:  # pragma: no cover - environment-specific dependency issue
    _SOUNDDEVICE_IMPORT_ERROR: OSError | None = exc

    class _UnavailableSoundDevice:
        @staticmethod
        def OutputStream(**_kwargs: object) -> object:
            raise RuntimeError(f"sounddevice unavailable: {_SOUNDDEVICE_IMPORT_ERROR}")

    sd = _UnavailableSoundDevice()  # type: ignore[assignment]
else:
    _SOUNDDEVICE_IMPORT_ERROR = None

from polyvoice_app import config as config_module

logger = logging.getLogger("polyvoice.tts_client")


@dataclass(frozen=True)
class TTSResult:
    ok: bool
    message: str = ""
    status: int | None = None


@dataclass(frozen=True)
class WavInfo:
    sample_rate: int
    channels: int
    sample_width: int
    dtype: str


class AudioPlayer:
    """Plays PCM chunks after parsing the WAV header from a streamed response."""

    def __init__(self) -> None:
        self._stream: sd.OutputStream | None = None

    def play_wav_stream(self, response: BinaryIO, cancel: threading.Event, chunk_size: int = 8192) -> TTSResult:
        try:
            header = _read_exact(response, 44, cancel)
            if cancel.is_set():
                return TTSResult(False, "cancelled")
            info = parse_wav_header(header)
            with sd.OutputStream(
                samplerate=info.sample_rate,
                channels=info.channels,
                dtype=info.dtype,
            ) as stream:
                self._stream = stream
                while not cancel.is_set():
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    if len(chunk) % info.sample_width:
                        chunk = chunk[: -(len(chunk) % info.sample_width)]
                    if chunk:
                        stream.write(np.frombuffer(chunk, dtype=info.dtype).reshape(-1, info.channels))
            return TTSResult(not cancel.is_set(), "cancelled" if cancel.is_set() else "")
        except Exception as exc:  # noqa: BLE001
            logger.exception("tts playback failed", extra={"event": "tts_playback_failed", "error": str(exc)})
            return TTSResult(False, str(exc))
        finally:
            self._stream = None

    def stop(self) -> None:
        if self._stream:
            try:
                self._stream.abort()
            except Exception:  # noqa: BLE001
                logger.debug("audio abort failed", exc_info=True)


class TTSClient:
    def __init__(self, cfg: config_module.Config, player: AudioPlayer | None = None, timeout_s: float = 8.0) -> None:
        self.cfg = cfg
        self.player = player or AudioPlayer()
        self.timeout_s = timeout_s
        self._lock = threading.Lock()
        self._cancel: threading.Event | None = None
        self._thread: threading.Thread | None = None
        self.last_result = TTSResult(True)

    def speak(self, text: str) -> threading.Thread:
        """Start speaking in the background, cancelling any previous utterance."""
        self.stop()
        cancel = threading.Event()
        thread = threading.Thread(target=self._speak_into_result, args=(text, cancel), daemon=True)
        with self._lock:
            self._cancel = cancel
            self._thread = thread
        thread.start()
        return thread

    def speak_blocking(self, text: str) -> TTSResult:
        self.stop()
        cancel = threading.Event()
        with self._lock:
            self._cancel = cancel
            self._thread = None
        result = self._speak(text, cancel)
        self.last_result = result
        return result

    def stop(self) -> None:
        with self._lock:
            cancel = self._cancel
            thread = self._thread
        if cancel:
            cancel.set()
        self.player.stop()
        if thread and thread.is_alive():
            thread.join(timeout=1.0)

    def _speak_into_result(self, text: str, cancel: threading.Event) -> None:
        result = self._speak(text, cancel)
        self.last_result = result

    def _speak(self, text: str, cancel: threading.Event) -> TTSResult:
        text = text.strip()
        if not text:
            return TTSResult(True, "empty")
        url = _speech_url(str(self.cfg.data["tts"].get("url", "http://127.0.0.1:7891")))
        body = json.dumps(
            {
                "input": text,
                "voice": str(self.cfg.data["tts"].get("voice", "f1")),
                "response_format": "wav",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                status = int(getattr(response, "status", 200))
                if status == 503:
                    return TTSResult(False, "TTS server is not ready", status)
                if status < 200 or status >= 300:
                    return TTSResult(False, f"TTS server returned HTTP {status}", status)
                return self.player.play_wav_stream(response, cancel)
        except urllib.error.HTTPError as exc:
            if exc.code == 503:
                return TTSResult(False, "TTS server is not ready", exc.code)
            return TTSResult(False, f"TTS server returned HTTP {exc.code}", exc.code)
        except TimeoutError:
            return TTSResult(False, "TTS request timed out")
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            return TTSResult(False, f"TTS unavailable: {reason}")


def parse_wav_header(header: bytes) -> WavInfo:
    if len(header) < 44 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
        raise ValueError("invalid WAV header")
    if header[12:16] != b"fmt ":
        raise ValueError("unsupported WAV header")
    audio_format, channels, sample_rate, _byte_rate, block_align, bits_per_sample = struct.unpack(
        "<HHIIHH", header[20:36]
    )
    if audio_format != 1:
        raise ValueError("only PCM WAV is supported")
    if header[36:40] != b"data":
        raise ValueError("unsupported WAV chunk layout")
    sample_width = bits_per_sample // 8
    if sample_width == 2:
        dtype = "int16"
    elif sample_width == 4:
        dtype = "int32"
    elif sample_width == 1:
        dtype = "uint8"
    else:
        raise ValueError(f"unsupported WAV bit depth: {bits_per_sample}")
    if block_align != channels * sample_width:
        raise ValueError("invalid WAV block alignment")
    return WavInfo(sample_rate=sample_rate, channels=channels, sample_width=sample_width, dtype=dtype)


def health_check(url: str, timeout_s: float = 1.5) -> bool:
    request = urllib.request.Request(url.rstrip("/") + "/health", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return 200 <= int(getattr(response, "status", 200)) < 300
    except urllib.error.URLError:
        return False


def _speech_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/v1/audio/speech"


def _read_exact(response: BinaryIO, size: int, cancel: threading.Event) -> bytes:
    out = bytearray()
    while len(out) < size and not cancel.is_set():
        chunk = response.read(size - len(out))
        if not chunk:
            break
        out.extend(chunk)
    if len(out) != size and not cancel.is_set():
        raise ValueError("truncated WAV header")
    return bytes(out)
