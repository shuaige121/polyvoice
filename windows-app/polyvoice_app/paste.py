"""Paste text into the focused window via Win32 clipboard and SendInput."""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("polyvoice.paste")

CF_UNICODETEXT = 13
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_V = 0x56


class PasteError(RuntimeError):
    """Raised when clipboard paste cannot be attempted."""


@dataclass(frozen=True)
class PasteResult:
    success: bool
    error: str | None = None


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


def paste_text(text: str, restore_delay_s: float = 0.15) -> PasteResult:
    clipboard = _clipboard()
    previous: str | None = None
    had_text = False
    try:
        clipboard.OpenClipboard()
        try:
            if clipboard.IsClipboardFormatAvailable(CF_UNICODETEXT):
                previous = clipboard.GetClipboardData(CF_UNICODETEXT)
                had_text = True
            clipboard.EmptyClipboard()
            clipboard.SetClipboardData(CF_UNICODETEXT, text)
        finally:
            clipboard.CloseClipboard()
    except Exception as exc:  # noqa: BLE001
        logger.exception("clipboard update failed", extra={"event": "clipboard_update_failed", "error": str(exc)})
        return PasteResult(False, str(exc))

    sent = _send_ctrl_v()
    if not sent:
        logger.warning("paste failed", extra={"event": "paste_failed", "error": "SendInput failed"})
        return PasteResult(False, "SendInput failed; text left on clipboard")

    time.sleep(restore_delay_s)
    if had_text:
        try:
            clipboard.OpenClipboard()
            try:
                clipboard.EmptyClipboard()
                clipboard.SetClipboardData(CF_UNICODETEXT, previous or "")
            finally:
                clipboard.CloseClipboard()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "clipboard restore failed",
                extra={"event": "clipboard_restore_failed", "error": str(exc)},
            )
    logger.info("paste complete", extra={"event": "paste_complete", "chars": len(text)})
    return PasteResult(True)


def _send_ctrl_v() -> bool:
    inputs = (INPUT * 4)(
        _keyboard_input(VK_CONTROL, 0),
        _keyboard_input(VK_V, 0),
        _keyboard_input(VK_V, KEYEVENTF_KEYUP),
        _keyboard_input(VK_CONTROL, KEYEVENTF_KEYUP),
    )
    sent = ctypes.windll.user32.SendInput(4, ctypes.byref(inputs), ctypes.sizeof(INPUT))
    return int(sent) == 4


def _keyboard_input(vk: int, flags: int) -> INPUT:
    return INPUT(
        type=INPUT_KEYBOARD,
        union=INPUT_UNION(ki=KEYBDINPUT(vk, 0, flags, 0, None)),
    )


def _clipboard() -> Any:
    try:
        import win32clipboard
    except ImportError as exc:
        raise PasteError("pywin32 is required for clipboard paste") from exc
    return win32clipboard
