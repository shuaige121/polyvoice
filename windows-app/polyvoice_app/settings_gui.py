"""Settings window for the Windows tray app."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from polyvoice_app import config as config_module
from polyvoice_app import hook_installer, paths, vocab
from polyvoice_app.recorder import list_microphones
from polyvoice_app.tts_client import TTSClient, health_check
from polyvoice_app.tray import open_log
from polyvoice_app.wizard import HotkeyButton, validate_hotkey_choice


class Worker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, func: Callable[[], object]) -> None:
        super().__init__()
        self.func = func

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.func())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class SettingsWindow(QWidget):
    config_changed = Signal()
    hotkey_changed = Signal()

    def __init__(self, cfg: config_module.Config) -> None:
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle("polyvoice settings")
        self.tabs = QTabWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        self.tabs.addTab(EngineTab(cfg, self.config_changed.emit), "Engine")
        self.tabs.addTab(MicHotkeyTab(cfg, self.config_changed.emit, self.hotkey_changed.emit), "Mic + Hotkey")
        self.tabs.addTab(VocabTab(cfg, self.config_changed.emit), "Vocab")
        self.tabs.addTab(TTSTab(cfg, self.config_changed.emit), "TTS & Hook")
        self.tabs.addTab(AdvancedTab(cfg, self.config_changed.emit), "Advanced")
        self._threads: list[QThread] = []


class EngineTab(QWidget):
    def __init__(self, cfg: config_module.Config, changed: Callable[[], None]) -> None:
        super().__init__()
        self.cfg = cfg
        self.changed = changed
        self.route = QComboBox()
        self.route.addItems(["local", "wsl"])
        self.route.setCurrentText(str(cfg.data["stt"].get("route", "local")))
        self.health = QLabel(engine_health_text(cfg))
        self.model_path = QLineEdit(str(cfg.data["stt"].get("model_dir") or paths.default_model_dir()))
        self.redownload = QPushButton("Re-download")
        self.redownload.clicked.connect(lambda: QMessageBox.information(self, "Model", "Model download is wired in Phase 4."))
        self.route.currentTextChanged.connect(self._save)
        self.model_path.editingFinished.connect(self._save)

        layout = QFormLayout(self)
        layout.addRow("Route", self.route)
        layout.addRow("Health", self.health)
        layout.addRow("Model path", self.model_path)
        layout.addRow("", self.redownload)

    def _save(self) -> None:
        self.cfg.data["stt"]["route"] = self.route.currentText()
        self.cfg.data["stt"]["model_dir"] = self.model_path.text().strip() or None
        self.health.setText(engine_health_text(self.cfg))
        self.changed()


class MicHotkeyTab(QWidget):
    def __init__(
        self,
        cfg: config_module.Config,
        changed: Callable[[], None],
        hotkey_changed: Callable[[], None],
    ) -> None:
        super().__init__()
        self.cfg = cfg
        self.changed = changed
        self.hotkey_changed = hotkey_changed
        self.mics = QComboBox()
        self.hotkey = HotkeyButton()
        self.hotkey.setText(current_hotkey_text(cfg))
        self.hotkey_status = QLabel("")
        self.vu = QProgressBar()
        self.vu.setRange(0, 100)
        self._vu_level = 0
        self._load_mics()
        save_hotkey = QPushButton("Save hotkey")
        save_hotkey.clicked.connect(self._save_hotkey)
        self.mics.currentIndexChanged.connect(self._save_mic)

        timer = QTimer(self)
        timer.timeout.connect(self._tick_vu)
        timer.start(120)

        row = QHBoxLayout()
        row.addWidget(self.hotkey)
        row.addWidget(save_hotkey)

        layout = QFormLayout(self)
        layout.addRow("Microphone", self.mics)
        layout.addRow("Input level", self.vu)
        layout.addRow("Hotkey", row)
        layout.addRow("", self.hotkey_status)

    def _load_mics(self) -> None:
        try:
            microphones = list_microphones()
        except Exception:
            microphones = []
        for mic in microphones:
            self.mics.addItem(str(mic["name"]), mic)
        if not microphones:
            self.mics.addItem("Default microphone", {"name": None, "index": None})

    def _save_mic(self) -> None:
        mic = self.mics.currentData() or {}
        self.cfg.data["mic"] = {"name": mic.get("name"), "index": mic.get("index")}
        self.changed()

    def _save_hotkey(self) -> None:
        ok, message = validate_hotkey_choice(self.hotkey.choice)
        self.hotkey_status.setText(message)
        if not ok:
            return
        self.cfg.data["hotkey"] = {
            "vk": self.hotkey.choice.vk,
            "modifiers": list(self.hotkey.choice.modifiers),
            "toggle": False,
        }
        self.hotkey_changed()

    def _tick_vu(self) -> None:
        self._vu_level = (self._vu_level + 13) % 100
        self.vu.setValue(self._vu_level)


class VocabTab(QWidget):
    def __init__(self, cfg: config_module.Config, changed: Callable[[], None]) -> None:
        super().__init__()
        self.cfg = cfg
        self.changed = changed
        self.count = QLabel(vocab_count_text())
        self.last_refresh = QLabel(last_refresh_text())
        self.status = QLabel("")
        self.scan = QCheckBox("Scan WSL history")
        self.scan.setChecked(bool(cfg.data.get("vocab", {}).get("scan_wsl_history", False)))
        refresh = QPushButton("Refresh Now")
        refresh.clicked.connect(self._refresh)
        self.scan.toggled.connect(self._save)
        layout = QFormLayout(self)
        layout.addRow("Count", self.count)
        layout.addRow("Last refresh", self.last_refresh)
        layout.addRow("", self.scan)
        layout.addRow("", refresh)
        layout.addRow("Status", self.status)
        self._threads: list[QThread] = []

    def _save(self, checked: bool) -> None:
        self.cfg.data.setdefault("vocab", {})["scan_wsl_history"] = checked
        self.changed()

    def _refresh(self) -> None:
        thread = QThread(self)
        worker = vocab.VocabScanWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.status.setText)
        worker.finished.connect(lambda _result: self.count.setText(vocab_count_text()))
        worker.finished.connect(lambda _result: self.last_refresh.setText(last_refresh_text()))
        worker.finished.connect(lambda result: self.status.setText(f"wrote {result.curated} entries"))
        worker.finished.connect(thread.quit)
        worker.failed.connect(lambda message: self.status.setText(message))
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._threads.remove(thread) if thread in self._threads else None)
        self._threads.append(thread)
        self.status.setText("starting WSL scan...")
        thread.start()


class TTSTab(QWidget):
    def __init__(self, cfg: config_module.Config, changed: Callable[[], None]) -> None:
        super().__init__()
        self.cfg = cfg
        self.changed = changed
        self.enabled = QCheckBox("Enable TTS")
        self.enabled.setChecked(bool(cfg.data["tts"].get("enabled", False)))
        self.url = QLineEdit(str(cfg.data["tts"].get("url", "http://127.0.0.1:7891")))
        self.voice = QComboBox()
        self.voice.addItems(["f1"])
        self.voice.setCurrentText(str(cfg.data["tts"].get("voice", "f1")))
        self.hook = QPushButton("Install Claude Code Stop hook")
        self.test = QPushButton("Test TTS")
        self.status = QLabel(hook_status_text(cfg))
        self._threads: list[QThread] = []
        self.hook.clicked.connect(self._toggle_hook)
        self.test.clicked.connect(self._test_tts)
        self.enabled.toggled.connect(self._save)
        self.url.editingFinished.connect(self._save)
        self.voice.currentTextChanged.connect(self._save)
        layout = QFormLayout(self)
        layout.addRow("", self.enabled)
        layout.addRow("URL", self.url)
        layout.addRow("Voice", self.voice)
        layout.addRow("", self.test)
        layout.addRow("", self.hook)
        layout.addRow("Status", self.status)
        self._sync_hook_button()

    def _save(self) -> None:
        self.cfg.data["tts"]["enabled"] = self.enabled.isChecked()
        self.cfg.data["tts"]["url"] = self.url.text().strip() or "http://127.0.0.1:7891"
        self.cfg.data["tts"]["voice"] = self.voice.currentText()
        self.status.setText(hook_status_text(self.cfg))
        self._sync_hook_button()
        self.changed()

    def _test_tts(self) -> None:
        self._start_worker(
            lambda: TTSClient(self.cfg).speak_blocking("polyvoice TTS works"),
            self._test_done,
        )
        self.status.setText("Playing TTS test phrase...")

    def _toggle_hook(self) -> None:
        def run() -> object:
            if bool(self.cfg.data.get("hook_installed")):
                return hook_installer.uninstall_hook(self.cfg)
            return hook_installer.install_hook(self.cfg)

        self._start_worker(run, self._hook_done)
        self.status.setText("Updating Claude Code hook...")

    def _sync_hook_button(self) -> None:
        installed = bool(self.cfg.data.get("hook_installed"))
        self.hook.setText("Uninstall Claude Code Stop hook" if installed else "Install Claude Code Stop hook")

    def _start_worker(self, func: Callable[[], object], finished: Callable[[object], None]) -> None:
        thread = QThread(self)
        worker = Worker(func)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(finished)
        worker.finished.connect(thread.quit)
        worker.failed.connect(self._worker_failed)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._threads.remove(thread) if thread in self._threads else None)
        self._threads.append(thread)
        thread.start()

    def _test_done(self, result: object) -> None:
        if getattr(result, "ok", False):
            self.status.setText("TTS test played.")
        else:
            self.status.setText(getattr(result, "message", "TTS test failed."))

    def _hook_done(self, result: object) -> None:
        self.status.setText(getattr(result, "message", "Hook updated."))
        self._sync_hook_button()
        self.changed()

    def _worker_failed(self, message: str) -> None:
        QMessageBox.warning(self, "polyvoice", message)
        self.status.setText(message)


class AdvancedTab(QWidget):
    def __init__(self, cfg: config_module.Config, changed: Callable[[], None]) -> None:
        super().__init__()
        self.cfg = cfg
        self.changed = changed
        self.log_level = QComboBox()
        self.log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level.setCurrentText(str(cfg.data.get("log_level", "INFO")))
        self.log_path = QLineEdit(str(paths.log_path()))
        self.stt_port = QSpinBox()
        self.stt_port.setRange(1, 65535)
        self.stt_port.setValue(7892)
        self.tts_port = QSpinBox()
        self.tts_port.setRange(1, 65535)
        self.tts_port.setValue(7891)
        open_button = QPushButton("Open Log")
        open_button.clicked.connect(open_log)
        reset = QPushButton("Reset config")
        reset.clicked.connect(self._reset)
        self.log_level.currentTextChanged.connect(self._save)

        layout = QFormLayout(self)
        layout.addRow("Log level", self.log_level)
        layout.addRow("Log path", self.log_path)
        layout.addRow("", open_button)
        layout.addRow("STT port", self.stt_port)
        layout.addRow("TTS port", self.tts_port)
        layout.addRow("", reset)

    def _save(self) -> None:
        self.cfg.data["log_level"] = self.log_level.currentText()
        self.changed()

    def _reset(self) -> None:
        if QMessageBox.question(self, "Reset config", "Reset settings to defaults?") != QMessageBox.StandardButton.Yes:
            return
        self.cfg.data.clear()
        self.cfg.data.update(config_module.default_settings())
        self.changed()


def engine_health_text(cfg: config_module.Config) -> str:
    if cfg.data["stt"].get("route") == "wsl":
        return f"WSL {cfg.data['stt'].get('wsl_url', 'http://127.0.0.1:7892')}"
    ready = paths.default_model_path().exists() and paths.default_tokens_path().exists()
    return "local ready" if ready else "local model missing"


def current_hotkey_text(cfg: config_module.Config) -> str:
    if cfg.hotkey_vk is None:
        return "Press the key combination you want"
    parts = [modifier.upper() for modifier in cfg.hotkey_modifiers]
    parts.append(f"VK 0x{cfg.hotkey_vk:02X}")
    return "+".join(parts)


def vocab_count_text() -> str:
    path = paths.hotwords_path()
    if not path.exists():
        return "0"
    count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#"))
    return str(count)


def last_refresh_text() -> str:
    path = paths.hotwords_path()
    if not path.exists():
        return "never"
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def hook_status_text(cfg: config_module.Config) -> str:
    installed = "installed" if bool(cfg.data.get("hook_installed")) else "not installed"
    url = str(cfg.data["tts"].get("url", "http://127.0.0.1:7891"))
    healthy = "healthy" if health_check(url) else "unavailable"
    return f"hook {installed}; TTS {healthy}"
