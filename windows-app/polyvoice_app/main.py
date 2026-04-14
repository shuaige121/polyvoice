"""PySide6 entrypoint for the Windows tray app."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QThread
from PySide6.QtWidgets import QApplication, QDialog

from polyvoice_app import config as config_module
from polyvoice_app import logging_setup, vocab
from polyvoice_app.dictation_controller import DictationController, StateChange
from polyvoice_app.hotkey import HotkeyConflictError, HotkeyListener, HotkeySpec
from polyvoice_app.paste import paste_text
from polyvoice_app.recorder import MicSelection, Recorder
from polyvoice_app.settings_gui import SettingsWindow
from polyvoice_app.stt import STTConfig, STTEngine, STTNotReadyError
from polyvoice_app.tts_client import TTSClient
from polyvoice_app.tray import TrayController, TrayStatus
from polyvoice_app.wizard import SetupWizard

logger = logging.getLogger("polyvoice.main")


class AppRuntime(QObject):
    def __init__(self, cfg: config_module.Config) -> None:
        super().__init__()
        self.cfg = cfg
        self.tray = TrayController(_tray_status_from_config(cfg))
        self.settings_window: SettingsWindow | None = None
        self.controller: DictationController | None = None
        self.hotkey: HotkeyListener | None = None
        self._threads: list[QThread] = []
        self._shutdown = False
        self._wire_tray()
        self._init_controller()
        self._register_hotkey()

    def show(self) -> None:
        self.tray.show()

    def shutdown(self) -> None:
        self._shutdown = True
        if self.hotkey:
            self.hotkey.stop()
            self.hotkey = None
        if self.controller and self.controller.state == "recording":
            try:
                self.controller.hotkey_release()
            except Exception:  # noqa: BLE001
                logger.exception("recorder stop during shutdown failed")
        if self.controller:
            self.controller.wait_idle(timeout=3)
        config_module.save_config(self.cfg)
        for thread in list(self._threads):
            thread.quit()
            thread.wait(3000)
        self.tray.hide()

    def _wire_tray(self) -> None:
        self.tray.settings_requested.connect(self._open_settings)
        self.tray.refresh_vocab_requested.connect(self.refresh_vocab)
        self.tray.toggle_tts_requested.connect(self._toggle_tts)
        self.tray.reconnect_wsl_requested.connect(self._reconnect_wsl)
        self.tray.quit_requested.connect(QApplication.instance().quit)

    def _init_controller(self) -> None:
        try:
            recorder = Recorder(
                MicSelection(
                    name=self.cfg.data["mic"].get("name"),
                    index=self.cfg.data["mic"].get("index"),
                ),
                max_recording_s=self.cfg.max_recording_s,
            )
            stt = _make_stt(self.cfg)
            if self.cfg.data["stt"].get("route") == "local" and not stt.model_ready():
                raise STTNotReadyError("STT unavailable - see Settings > Engine")
            self.controller = DictationController(recorder=recorder, stt=stt, paste=paste_text)
            self.controller.add_state_callback(self._on_state_change)
        except Exception as exc:  # noqa: BLE001
            logger.exception("stt init failed", extra={"event": "stt_init_failed", "error": str(exc)})
            self.tray.update_status(_tray_status_from_config(self.cfg, "error", "unavailable"))
            self.tray.show_message("polyvoice", "STT unavailable - see Settings > Engine", error=True)

    def _register_hotkey(self) -> None:
        if not config_module.has_hotkey(self.cfg):
            self.tray.show_message("polyvoice", "Open Settings to choose a voice hotkey.")
            return
        if self.hotkey:
            self.hotkey.stop()
            self.hotkey = None
        try:
            self.hotkey = HotkeyListener(
                _hotkey_spec(self.cfg),
                on_press=self._hotkey_press,
                on_release=self._hotkey_release,
            )
            self.hotkey.start()
        except HotkeyConflictError:
            logger.exception("hotkey conflict", extra={"event": "hotkey_conflict"})
            self.tray.show_message("polyvoice", "Hotkey conflict - open Settings to change", error=True)
            self.tray.set_state("error")
        except Exception as exc:  # noqa: BLE001
            logger.exception("hotkey register failed", extra={"event": "hotkey_register_failed", "error": str(exc)})
            self.tray.show_message("polyvoice", f"Hotkey unavailable: {exc}", error=True)
            self.tray.set_state("error")

    def _hotkey_press(self) -> None:
        if self.controller:
            self.controller.hotkey_press()

    def _hotkey_release(self) -> None:
        if self.controller:
            self.controller.hotkey_release()

    def _on_state_change(self, change: StateChange) -> None:
        if self._shutdown:
            return
        if change.new == "error":
            message = self.controller.last_error if self.controller else "Dictation failed"
            self.tray.show_message("polyvoice", message or "Dictation failed", error=True)
        self.tray.set_state(change.new)

    def _open_settings(self) -> None:
        if self.settings_window is None:
            self.settings_window = SettingsWindow(self.cfg)
            self.settings_window.hotkey_changed.connect(self._on_hotkey_changed)
            self.settings_window.config_changed.connect(self._on_config_changed)
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def _on_hotkey_changed(self) -> None:
        config_module.save_config(self.cfg)
        self._register_hotkey()

    def _on_config_changed(self) -> None:
        config_module.save_config(self.cfg)
        self.tray.update_status(_tray_status_from_config(self.cfg, self.tray.status.state, self.tray.status.stt_state))

    def _toggle_tts(self, enabled: bool) -> None:
        self.cfg.data["tts"]["enabled"] = enabled
        self._on_config_changed()

    def _reconnect_wsl(self) -> None:
        try:
            distros = vocab.enumerate_wsl_distros()
        except Exception as exc:  # noqa: BLE001
            self.tray.show_message("polyvoice", f"WSL unavailable: {exc}", error=True)
            return
        self.tray.show_message("polyvoice", f"Detected WSL: {', '.join(distros) or 'none'}")

    def refresh_vocab(self) -> None:
        thread = QThread(self)
        worker = vocab.VocabScanWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda: self.tray.set_state("idle"))
        worker.finished.connect(thread.quit)
        worker.failed.connect(lambda message: self.tray.show_message("polyvoice", message, error=True))
        worker.failed.connect(lambda _message: self.tray.set_state("error"))
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._threads.remove(thread) if thread in self._threads else None)
        self._threads.append(thread)
        self.tray.set_state("vocab_refresh")
        thread.start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="polyvoice Windows tray app")
    parser.add_argument("--dry-wizard", action="store_true", help="show the wizard without blocking on the finish hotkey test")
    parser.add_argument("--tts-test", help="speak a phrase using the configured TTS route and exit")
    parser.add_argument("--scan-wsl-vocab", action="store_true", help="scan WSL Claude Code history and exit")
    args = parser.parse_args(argv)

    first_run = config_module.first_run()
    cfg = config_module.load_config()
    logging_setup.setup_logging(str(cfg.data.get("log_level", "INFO")))

    if args.tts_test is not None:
        result = TTSClient(cfg).speak_blocking(args.tts_test)
        if not result.ok:
            print(result.message or "TTS failed", file=sys.stderr)
            return 2
        return 0

    if args.scan_wsl_vocab:
        result = vocab.refresh_from_wsl(progress=lambda message: print(message, flush=True))
        print(
            f"scanned {result.messages} messages, wrote {result.curated} vocab entries "
            f"to {result.hotwords_path}"
        )
        return 0

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)

    if first_run or args.dry_wizard:
        wizard = SetupWizard(cfg, dry_run=args.dry_wizard)
        result = wizard.exec()
        if result != QDialog.DialogCode.Accepted:
            return 1
        cfg = wizard.config
        config_module.save_config(cfg)

    runtime = AppRuntime(cfg)
    runtime.show()
    app.aboutToQuit.connect(runtime.shutdown)
    return int(app.exec())


def _make_stt(cfg: config_module.Config) -> STTEngine:
    raw = cfg.data["stt"]
    model_dir = raw.get("model_dir")
    return STTEngine(
        STTConfig(
            route=str(raw.get("route", "local")),
            wsl_url=str(raw.get("wsl_url", "http://127.0.0.1:7892")),
            model_dir=Path(model_dir) if model_dir else None,
        )
    )


def _hotkey_spec(cfg: config_module.Config) -> HotkeySpec:
    vk = cfg.hotkey_vk
    if vk is None:
        raise HotkeyConflictError("no hotkey configured")
    return HotkeySpec(vk=vk, modifiers=tuple(cfg.hotkey_modifiers), toggle=cfg.hotkey_toggle)


def _tray_status_from_config(
    cfg: config_module.Config,
    state: str = "idle",
    stt_state: str = "ready",
) -> TrayStatus:
    return TrayStatus(
        state=state,
        stt_route=str(cfg.data["stt"].get("route", "local")),
        stt_state=stt_state,
        mic_name=str(cfg.data["mic"].get("name") or "default"),
        tts_enabled=bool(cfg.data["tts"].get("enabled", False)),
    )


if __name__ == "__main__":
    raise SystemExit(main())
