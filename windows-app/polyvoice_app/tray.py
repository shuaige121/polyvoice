"""System tray UI for the Windows app."""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from polyvoice_app import paths

logger = logging.getLogger("polyvoice.tray")


@dataclass
class TrayStatus:
    state: str = "idle"
    stt_route: str = "local"
    stt_state: str = "ready"
    mic_name: str = "default"
    tts_enabled: bool = False
    ttfb_ms: int | None = None


class TrayController(QObject):
    """QSystemTrayIcon wrapper with Phase 2 actions and state colors."""

    refresh_vocab_requested = Signal()
    toggle_tts_requested = Signal(bool)
    reconnect_wsl_requested = Signal()
    settings_requested = Signal()
    quit_requested = Signal()
    voice_toggled = Signal(bool)

    def __init__(self, status: TrayStatus | None = None) -> None:
        super().__init__()
        self.status = status or TrayStatus()
        self.voice_enabled = True
        self.tray = QSystemTrayIcon(self)
        self.menu = QMenu()
        self._voice_action = QAction("Voice: on", self.menu)
        self._voice_action.setCheckable(True)
        self._voice_action.setChecked(True)
        self._tts_action = QAction("Toggle TTS", self.menu)
        self._build_menu()
        self.update_status(self.status)

    def show(self) -> None:
        self.tray.show()

    def hide(self) -> None:
        self.tray.hide()

    def show_message(self, title: str, message: str, error: bool = False) -> None:
        icon = QSystemTrayIcon.MessageIcon.Critical if error else QSystemTrayIcon.MessageIcon.Information
        self.tray.showMessage(title, message, icon, 5000)

    def update_status(self, status: TrayStatus) -> None:
        self.status = status
        self.tray.setIcon(_state_icon(status.state))
        self.tray.setToolTip(tooltip_for_status(status))

    def set_state(self, state: str, stt_state: str | None = None) -> None:
        status = TrayStatus(**self.status.__dict__)
        status.state = state
        if stt_state:
            status.stt_state = stt_state
        self.update_status(status)

    def _build_menu(self) -> None:
        self._voice_action.triggered.connect(self._on_voice_toggled)
        self.menu.addAction(self._voice_action)
        self.menu.addSeparator()

        refresh_action = QAction("Refresh vocab", self.menu)
        refresh_action.triggered.connect(self.refresh_vocab_requested.emit)
        self.menu.addAction(refresh_action)

        self._tts_action.triggered.connect(self._on_tts_toggled)
        self.menu.addAction(self._tts_action)

        reconnect_action = QAction("Reconnect WSL", self.menu)
        reconnect_action.triggered.connect(self.reconnect_wsl_requested.emit)
        self.menu.addAction(reconnect_action)

        self.menu.addSeparator()
        settings_action = QAction("Settings", self.menu)
        settings_action.triggered.connect(self.settings_requested.emit)
        self.menu.addAction(settings_action)

        log_action = QAction("Open Log", self.menu)
        log_action.triggered.connect(open_log)
        self.menu.addAction(log_action)

        self.menu.addSeparator()
        quit_action = QAction("Quit", self.menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        self.menu.addAction(quit_action)

        self.tray.setContextMenu(self.menu)

    def _on_voice_toggled(self, checked: bool) -> None:
        self.voice_enabled = checked
        self._voice_action.setText("Voice: on" if checked else "Voice: off")
        self.voice_toggled.emit(checked)

    def _on_tts_toggled(self) -> None:
        status = TrayStatus(**self.status.__dict__)
        status.tts_enabled = not status.tts_enabled
        self.update_status(status)
        self.toggle_tts_requested.emit(status.tts_enabled)


def tooltip_for_status(status: TrayStatus) -> str:
    tts = "on" if status.tts_enabled else "off"
    ttfb = f"{status.ttfb_ms} ms" if status.ttfb_ms is not None else "-"
    return (
        f"polyvoice - STT: {status.stt_route} ({status.stt_state}) | "
        f"Mic: {status.mic_name or 'default'} | TTS: {tts} | TTFB: {ttfb}"
    )


def open_log() -> None:
    paths.ensure_app_dirs()
    log_path = paths.log_path()
    if os.name == "nt":
        subprocess.Popen(["notepad.exe", str(log_path)])  # noqa: S603,S607
    else:
        logger.info("open log requested", extra={"event": "open_log", "path": str(log_path)})


def _state_icon(state: str) -> QIcon:
    if state in {"recording", "transcribing", "pasting", "vocab_refresh"}:
        color = "#d4a017"
    elif state in {"error", "stt_init_failed", "mic_unavailable", "model_missing"}:
        color = "#c62828"
    else:
        color = "#2e7d32"
    pixmap = QPixmap(64, 64)
    pixmap.fill("transparent")
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(color)
    painter.setPen(color)
    painter.drawEllipse(8, 8, 48, 48)
    painter.end()
    return QIcon(pixmap)
