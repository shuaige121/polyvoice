"""Global hotkey handling with Win32 RegisterHotKey and GetAsyncKeyState."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("polyvoice.hotkey")

MODIFIER_FLAGS = {
    "alt": 0x0001,
    "control": 0x0002,
    "ctrl": 0x0002,
    "shift": 0x0004,
    "win": 0x0008,
}
WM_HOTKEY = 0x0312


class HotkeyError(RuntimeError):
    """Base hotkey error."""


class HotkeyConflictError(HotkeyError):
    """Raised when RegisterHotKey fails."""


@dataclass(frozen=True)
class HotkeySpec:
    vk: int
    modifiers: tuple[str, ...] = ("alt",)
    toggle: bool = False

    @property
    def modifier_flags(self) -> int:
        flags = 0
        for modifier in self.modifiers:
            try:
                flags |= MODIFIER_FLAGS[modifier.lower()]
            except KeyError as exc:
                raise HotkeyError(f"unsupported modifier: {modifier}") from exc
        return flags


class HotkeyListener:
    """Message-pump based hotkey listener."""

    def __init__(
        self,
        spec: HotkeySpec,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        hotkey_id: int = 1,
        poll_hz: float = 20,
    ) -> None:
        self.spec = spec
        self.on_press = on_press
        self.on_release = on_release
        self.hotkey_id = hotkey_id
        self.poll_hz = poll_hz
        self._stop = threading.Event()
        self._registered = threading.Event()
        self._thread: threading.Thread | None = None
        self._release_thread: threading.Thread | None = None
        self._toggle_down = False
        self._start_error: BaseException | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._registered.clear()
        self._thread = threading.Thread(target=self._run, name="polyvoice-hotkey", daemon=True)
        self._thread.start()
        if not self._registered.wait(timeout=2):
            raise HotkeyError("hotkey listener did not start")
        if self._start_error:
            raise self._start_error

    def stop(self) -> None:
        self._stop.set()
        try:
            _win32gui().PostThreadMessage(self._thread.ident if self._thread else 0, 0x0012, 0, 0)
        except Exception:  # noqa: BLE001
            pass
        if self._thread:
            self._thread.join(timeout=2)
        if self._release_thread:
            self._release_thread.join(timeout=2)

    def _run(self) -> None:
        try:
            win32gui = _win32gui()
        except Exception as exc:  # noqa: BLE001
            self._start_error = exc
            self._registered.set()
            return
        try:
            ok = win32gui.RegisterHotKey(None, self.hotkey_id, self.spec.modifier_flags, self.spec.vk)
        except Exception as exc:  # noqa: BLE001
            self._start_error = HotkeyConflictError(f"failed to register hotkey: {exc}")
            self._registered.set()
            return
        if not ok:
            self._start_error = HotkeyConflictError("failed to register hotkey")
            self._registered.set()
            return
        self._registered.set()
        logger.info(
            "hotkey registered",
            extra={
                "event": "hotkey_registered",
                "vk": self.spec.vk,
                "modifiers": list(self.spec.modifiers),
            },
        )
        try:
            while not self._stop.is_set():
                message = win32gui.GetMessage(None, 0, 0)
                if not message:
                    break
                msg = _message_id(message)
                if msg == WM_HOTKEY:
                    self._handle_hotkey()
                else:
                    win32gui.TranslateMessage(message)
                    win32gui.DispatchMessage(message)
        finally:
            try:
                win32gui.UnregisterHotKey(None, self.hotkey_id)
            except Exception:  # noqa: BLE001
                logger.exception("hotkey unregister failed", extra={"event": "hotkey_unregister_failed"})
            logger.info("hotkey stopped", extra={"event": "hotkey_stopped"})

    def _handle_hotkey(self) -> None:
        if self.spec.toggle:
            self._toggle_down = not self._toggle_down
            if self._toggle_down:
                self.on_press()
            else:
                self.on_release()
            return
        self.on_press()
        if self._release_thread and self._release_thread.is_alive():
            return
        self._release_thread = threading.Thread(
            target=self._poll_release,
            name="polyvoice-hotkey-release",
            daemon=True,
        )
        self._release_thread.start()

    def _poll_release(self) -> None:
        win32api = _win32api()
        interval = 1 / self.poll_hz
        while not self._stop.is_set():
            if not (win32api.GetAsyncKeyState(self.spec.vk) & 0x8000):
                self.on_release()
                return
            time.sleep(interval)


def parse_modifiers(modifiers: list[str] | tuple[str, ...]) -> int:
    return HotkeySpec(vk=0, modifiers=tuple(modifiers)).modifier_flags


def _message_id(message: Any) -> int:
    if hasattr(message, "message"):
        return int(message.message)
    if isinstance(message, tuple) and len(message) > 1:
        return int(message[1])
    return -1


def _win32gui() -> Any:
    try:
        import win32gui
    except ImportError as exc:
        raise HotkeyError("pywin32 is required for global hotkeys") from exc
    return win32gui


def _win32api() -> Any:
    try:
        import win32api
    except ImportError as exc:
        raise HotkeyError("pywin32 is required for hotkey release polling") from exc
    return win32api
