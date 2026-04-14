"""Dictation state machine for push-to-talk transcription and paste."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from polyvoice_app import postprocess
from polyvoice_app.paste import PasteResult, paste_text

logger = logging.getLogger("polyvoice.dictation_controller")

State = Literal["idle", "recording", "transcribing", "pasting", "error"]


class RecorderLike(Protocol):
    max_recording_s: float

    def start(self) -> None: ...

    def stop_bytes(self) -> bytes: ...


class STTLike(Protocol):
    def transcribe(self, pcm_bytes: bytes, sr: int = 16000) -> str: ...


@dataclass(frozen=True)
class StateChange:
    old: State
    new: State
    event: str


class DictationController:
    def __init__(
        self,
        recorder: RecorderLike,
        stt: STTLike,
        paste: Callable[[str], PasteResult] = paste_text,
        postprocessor: Callable[[str], str] = postprocess.process_text,
        error_reset_s: float = 2,
    ) -> None:
        self.recorder = recorder
        self.stt = stt
        self.paste = paste
        self.postprocessor = postprocessor
        self.error_reset_s = error_reset_s
        self.state: State = "idle"
        self.last_error: str | None = None
        self.last_text: str = ""
        self._lock = threading.RLock()
        self._recording_timer: threading.Timer | None = None
        self._worker: threading.Thread | None = None
        self._state_callbacks: list[Callable[[StateChange], None]] = []

    def add_state_callback(self, callback: Callable[[StateChange], None]) -> None:
        self._state_callbacks.append(callback)

    def hotkey_press(self) -> None:
        with self._lock:
            if self.state != "idle":
                logger.info(
                    "hotkey press ignored",
                    extra={"event": "hotkey_press_ignored", "state": self.state},
                )
                return
            try:
                self.recorder.start()
            except Exception as exc:  # noqa: BLE001
                self._handle_error(exc)
                return
            self._transition("recording", "hotkey_press")
            self._recording_timer = threading.Timer(self.recorder.max_recording_s, self.timeout)
            self._recording_timer.daemon = True
            self._recording_timer.start()

    def hotkey_release(self) -> None:
        with self._lock:
            if self.state != "recording":
                logger.info(
                    "hotkey release ignored",
                    extra={"event": "hotkey_release_ignored", "state": self.state},
                )
                return
            self._cancel_timer()
            self._transition("transcribing", "hotkey_release")
        self._start_worker()

    def timeout(self) -> None:
        with self._lock:
            if self.state != "recording":
                return
            logger.info("recording timeout", extra={"event": "recording_timeout", "state": self.state})
        self.hotkey_release()

    def wait_idle(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                if self.state == "idle":
                    return True
                worker = self._worker
            if worker and worker.is_alive():
                remaining = None if deadline is None else max(0, deadline - time.monotonic())
                worker.join(timeout=min(0.05, remaining) if remaining is not None else 0.05)
            else:
                time.sleep(0.01)
            if deadline is not None and time.monotonic() >= deadline:
                return False

    def _start_worker(self) -> None:
        self._worker = threading.Thread(target=self._run_pipeline, name="polyvoice-dictation", daemon=True)
        self._worker.start()

    def _run_pipeline(self) -> None:
        try:
            pcm = self.recorder.stop_bytes()
            text = self.stt.transcribe(pcm, sr=16000)
            text = self.postprocessor(text)
            self.last_text = text
            self._transition("pasting", "transcribe_done")
            result = self.paste(text)
            if not result.success:
                raise RuntimeError(result.error or "paste failed")
            self._transition("idle", "paste_done")
        except Exception as exc:  # noqa: BLE001
            self._handle_error(exc)

    def _transition(self, new_state: State, event: str) -> None:
        with self._lock:
            old = self.state
            self.state = new_state
        logger.info("state transition", extra={"event": event, "state": new_state, "old_state": old})
        change = StateChange(old=old, new=new_state, event=event)
        for callback in self._state_callbacks:
            try:
                callback(change)
            except Exception:  # noqa: BLE001
                logger.exception("state callback failed", extra={"event": "state_callback_failed"})

    def _handle_error(self, exc: BaseException) -> None:
        self._cancel_timer()
        self.last_error = str(exc)
        logger.exception(
            "dictation error",
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={"event": "dictation_error", "error": str(exc)},
        )
        self._transition("error", "error")
        timer = threading.Timer(self.error_reset_s, self._reset_from_error)
        timer.daemon = True
        timer.start()

    def _reset_from_error(self) -> None:
        with self._lock:
            if self.state == "error":
                self._transition("idle", "error_reset")

    def _cancel_timer(self) -> None:
        if self._recording_timer:
            self._recording_timer.cancel()
            self._recording_timer = None
