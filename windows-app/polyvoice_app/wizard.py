"""First-run setup wizard for the Windows tray app."""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from polyvoice_app import config as config_module
from polyvoice_app import hook_installer, vocab
from polyvoice_app.dictation_controller import DictationController, StateChange
from polyvoice_app.hotkey import HotkeyListener, HotkeySpec
from polyvoice_app.paste import PasteResult
from polyvoice_app.recorder import MicSelection, Recorder, list_microphones
from polyvoice_app.stt import STTConfig, STTEngine
from polyvoice_app.tts_client import TTSClient

logger = logging.getLogger("polyvoice.wizard")

EXPECTED_TEST_PHRASE = "你好 polyvoice 测试一下"


@dataclass(frozen=True)
class HotkeyChoice:
    vk: int | None
    modifiers: tuple[str, ...] = ()


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


class SetupWizard(QWizard):
    def __init__(self, cfg: config_module.Config, dry_run: bool = False) -> None:
        super().__init__()
        self.config = cfg
        self.dry_run = dry_run
        self._threads: list[QThread] = []
        self.setWindowTitle("polyvoice setup")
        self.addPage(WelcomePage())
        self.addPage(EnginePage(cfg, self))
        self.addPage(MicHotkeyPage(cfg, dry_run=dry_run))
        self.addPage(VocabPage(cfg, self))
        self.addPage(TTSPage(cfg, self))
        self.addPage(FinishPage(cfg, dry_run=dry_run))
        self.finished.connect(lambda _result: self._stop_threads())

    def start_worker(
        self,
        func: Callable[[], object],
        finished: Callable[[object], None],
        failed: Callable[[str], None],
    ) -> None:
        thread = QThread(self)
        worker = Worker(func)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(finished)
        worker.finished.connect(thread.quit)
        worker.failed.connect(failed)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._threads.remove(thread) if thread in self._threads else None)
        self._threads.append(thread)
        thread.start()

    def _stop_threads(self) -> None:
        for thread in list(self._threads):
            thread.quit()
            thread.wait(3000)


class WelcomePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Set up voice for Claude Code")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("This wizard configures dictation, recognition, and optional spoken replies."))


class EnginePage(QWizardPage):
    def __init__(self, cfg: config_module.Config, wizard: SetupWizard) -> None:
        super().__init__()
        self.cfg = cfg
        self.wizard_ref = wizard
        self.setTitle("Engine detection")
        self.status = QLabel("Checking WSL polyvoice STT at http://127.0.0.1:7892/health ...")
        self.use_wsl = QRadioButton("Use WSL polyvoice STT (saves 240 MB)")
        self.download_local = QRadioButton("Download local SenseVoice engine")
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()

        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.use_wsl)
        layout.addWidget(self.download_local)
        layout.addWidget(self.progress)

    def initializePage(self) -> None:
        self.wizard_ref.start_worker(probe_wsl_stt, self._probe_done, self._probe_failed)

    def validatePage(self) -> bool:
        if self.use_wsl.isChecked():
            self.cfg.data["stt"]["route"] = "wsl"
        else:
            self.cfg.data["stt"]["route"] = "local"
        return True

    def _probe_done(self, healthy: object) -> None:
        if bool(healthy):
            self.status.setText("Found polyvoice STT on WSL. You can use it and skip the local model download.")
            self.use_wsl.setChecked(True)
        else:
            self._start_download()

    def _probe_failed(self, message: str) -> None:
        self.status.setText(f"WSL polyvoice STT unavailable: {message}")
        self._start_download()

    def _start_download(self) -> None:
        self.download_local.setChecked(True)
        self.progress.show()
        self.status.setText("Downloading SenseVoice engine (240 MB)...")
        self.wizard_ref.start_worker(run_download_stub, self._download_done, self._download_failed)

    def _download_done(self, output: object) -> None:
        self.progress.hide()
        self.status.setText(str(output) or "model download not implemented yet - using WSL fallback or halting wizard")

    def _download_failed(self, message: str) -> None:
        self.progress.hide()
        self.status.setText(f"model download not implemented yet - using WSL fallback or halting wizard ({message})")


class HotkeyButton(QPushButton):
    captured = Signal(object)

    def __init__(self) -> None:
        super().__init__("Press the key combination you want")
        self.choice = HotkeyChoice(None)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        modifiers = modifiers_from_qt(event.modifiers())
        vk = qt_key_to_vk(event.key())
        self.choice = HotkeyChoice(vk=vk, modifiers=tuple(modifiers))
        self.setText(describe_hotkey_choice(self.choice))
        self.captured.emit(self.choice)


class MicHotkeyPage(QWizardPage):
    def __init__(self, cfg: config_module.Config, dry_run: bool = False) -> None:
        super().__init__()
        self.cfg = cfg
        self.dry_run = dry_run
        self.setTitle("Mic + hotkey")
        self.mics = QComboBox()
        self.vu = QProgressBar()
        self.vu.setRange(0, 100)
        self.hotkey_button = HotkeyButton()
        self.hotkey_status = QLabel("No hotkey selected.")
        self._vu_level = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_vu)

        layout = QFormLayout(self)
        layout.addRow("Microphone", self.mics)
        layout.addRow("Input level", self.vu)
        layout.addRow("Hotkey", self.hotkey_button)
        layout.addRow("", self.hotkey_status)

    def initializePage(self) -> None:
        self.mics.clear()
        try:
            microphones = list_microphones()
        except Exception as exc:  # noqa: BLE001
            logger.warning("microphones unavailable", extra={"event": "microphones_unavailable", "error": str(exc)})
            microphones = []
        for mic in microphones:
            self.mics.addItem(str(mic["name"]), mic)
        if not microphones:
            self.mics.addItem("Default microphone", {"name": None, "index": None})
        self._timer.start(120)

    def cleanupPage(self) -> None:
        self._timer.stop()

    def validatePage(self) -> bool:
        choice = self.hotkey_button.choice
        ok, message = validate_hotkey_choice(choice, accept_unregistered=self.dry_run)
        if not ok:
            self.hotkey_status.setText(message)
            QMessageBox.warning(self, "Hotkey", message)
            return False
        mic = self.mics.currentData() or {}
        self.cfg.data["mic"] = {"name": mic.get("name"), "index": mic.get("index")}
        self.cfg.data["hotkey"] = {
            "vk": choice.vk,
            "modifiers": list(choice.modifiers),
            "toggle": False,
        }
        return True

    def _tick_vu(self) -> None:
        self._vu_level = (self._vu_level + 17) % 100
        self.vu.setValue(self._vu_level)


class VocabPage(QWizardPage):
    def __init__(self, cfg: config_module.Config, wizard: SetupWizard) -> None:
        super().__init__()
        self.cfg = cfg
        self.wizard_ref = wizard
        self.setTitle("Enhance recognition")
        self.checkbox = QCheckBox("Improve recognition from your Claude Code history? Stays on this machine.")
        layout = QVBoxLayout(self)
        layout.addWidget(self.checkbox)

    def initializePage(self) -> None:
        self.checkbox.setChecked(has_wsl_claude_projects_hint())

    def validatePage(self) -> bool:
        self.cfg.data.setdefault("vocab", {})["scan_wsl_history"] = self.checkbox.isChecked()
        self.cfg.data["vocab"]["refresh_queued"] = self.checkbox.isChecked()
        return True


class TTSPage(QWizardPage):
    def __init__(self, cfg: config_module.Config, wizard: SetupWizard) -> None:
        super().__init__()
        self.cfg = cfg
        self.wizard_ref = wizard
        self.setTitle("Auto-speak replies")
        self.checkbox = QCheckBox("Let Claude speak responses aloud via polyvoice TTS?")
        self.hook = QCheckBox("Install Claude Code Stop hook")
        self.test = QPushButton("Play test phrase")
        self.status = QLabel("Checking WSL polyvoice TTS at http://127.0.0.1:7891/health ...")
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.checkbox)
        layout.addWidget(self.test)
        layout.addWidget(self.hook)
        self.checkbox.setChecked(False)
        self.hook.setChecked(False)
        self.hook.setEnabled(False)
        self.test.setEnabled(False)
        self.test.clicked.connect(self._play_test)

    def initializePage(self) -> None:
        self.wizard_ref.start_worker(probe_wsl_tts, self._tts_done, self._tts_failed)

    def validatePage(self) -> bool:
        self.cfg.data["tts"]["enabled"] = self.checkbox.isChecked()
        if self.checkbox.isChecked() and self.hook.isChecked():
            try:
                result = hook_installer.install_hook(self.cfg)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "Hook", str(exc))
                return False
            self.status.setText(result.message)
        else:
            self.cfg.data["hook_installed"] = False
        return True

    def _tts_done(self, healthy: object) -> None:
        if bool(healthy):
            self.status.setText("WSL polyvoice TTS is available.")
            self.checkbox.setEnabled(True)
            self.hook.setEnabled(True)
            self.test.setEnabled(True)
        else:
            self._tts_failed("not healthy")

    def _tts_failed(self, message: str) -> None:
        self.status.setText(f"WSL polyvoice TTS unavailable: {message}")
        self.checkbox.setChecked(False)
        self.checkbox.setEnabled(False)
        self.hook.setEnabled(False)
        self.test.setEnabled(False)

    def _play_test(self) -> None:
        self.cfg.data["tts"]["enabled"] = True
        self.wizard_ref.start_worker(
            lambda: TTSClient(self.cfg).speak_blocking("polyvoice TTS works"),
            self._test_done,
            self._tts_failed,
        )
        self.status.setText("Playing TTS test phrase...")

    def _test_done(self, result: object) -> None:
        if getattr(result, "ok", False):
            self.status.setText("TTS test played.")
        else:
            self.status.setText(getattr(result, "message", "TTS test failed."))


class FinishPage(QWizardPage):
    state_changed = Signal(str, str)

    def __init__(self, cfg: config_module.Config, dry_run: bool = False) -> None:
        super().__init__()
        self.cfg = cfg
        self.dry_run = dry_run
        self.controller: DictationController | None = None
        self.listener: HotkeyListener | None = None
        self.setTitle("Finish")
        self.input = QLineEdit()
        self.input.setPlaceholderText(EXPECTED_TEST_PHRASE)
        self.feedback = QLabel("Press your hotkey and say 你好 polyvoice 测试一下")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Press your hotkey and say 你好 polyvoice 测试一下"))
        layout.addWidget(self.input)
        layout.addWidget(self.feedback)
        self.input.textChanged.connect(self._update_feedback)
        self.state_changed.connect(self._on_state_changed)

    def initializePage(self) -> None:
        if self.dry_run:
            self.feedback.setText("Dry wizard mode: final hotkey test is skipped.")
            return
        try:
            recorder = Recorder(
                MicSelection(
                    name=self.cfg.data["mic"].get("name"),
                    index=self.cfg.data["mic"].get("index"),
                ),
                max_recording_s=self.cfg.max_recording_s,
            )
            stt = make_stt(self.cfg)
            self.controller = DictationController(
                recorder=recorder,
                stt=stt,
                paste=lambda _text: PasteResult(True),
            )
            self.controller.add_state_callback(self._controller_state_changed)
            self.listener = HotkeyListener(
                HotkeySpec(
                    vk=int(self.cfg.data["hotkey"]["vk"]),
                    modifiers=tuple(self.cfg.data["hotkey"].get("modifiers", [])),
                ),
                on_press=self.controller.hotkey_press,
                on_release=self.controller.hotkey_release,
            )
            self.listener.start()
            self.feedback.setText("Press your hotkey and say 你好 polyvoice 测试一下")
        except Exception as exc:  # noqa: BLE001
            logger.exception("wizard finish test unavailable", extra={"event": "wizard_finish_test_unavailable"})
            self.feedback.setText(f"Live test unavailable: {exc}. You can finish and adjust in Settings.")

    def cleanupPage(self) -> None:
        if self.listener:
            self.listener.stop()
            self.listener = None

    def isComplete(self) -> bool:
        return self.dry_run or bool(self.input.text().strip())

    def validatePage(self) -> bool:
        self.cleanupPage()
        if self.dry_run:
            return True
        return bool(self.input.text().strip())

    def _controller_state_changed(self, change: StateChange) -> None:
        text = self.controller.last_text if self.controller else ""
        if change.new == "idle" and text:
            self.state_changed.emit("recognized", text)
        elif change.new == "error":
            error = self.controller.last_error if self.controller else "test failed"
            self.state_changed.emit("error", error or "test failed")
        else:
            self.state_changed.emit(change.new, "")

    def _on_state_changed(self, state: str, text: str) -> None:
        if state == "recognized":
            self.input.setText(text)
            return
        if state == "error":
            self.feedback.setText(text)
            self.feedback.setStyleSheet("color: #c62828")
            return
        if state in {"recording", "transcribing"}:
            self.feedback.setText(f"{state}...")
            self.feedback.setStyleSheet("color: #b26a00")

    def _update_feedback(self, text: str) -> None:
        if phrase_matches_expected(text):
            self.feedback.setText("Match looks good.")
            self.feedback.setStyleSheet("color: #2e7d32")
        elif text.strip():
            self.feedback.setText("Recognized text is different. You can still finish and adjust in Settings.")
            self.feedback.setStyleSheet("color: #b26a00")
        else:
            self.feedback.setText("Press your hotkey and say 你好 polyvoice 测试一下")
            self.feedback.setStyleSheet("")
        self.completeChanged.emit()


def probe_wsl_stt() -> bool:
    return probe_health("http://127.0.0.1:7892/health")


def probe_wsl_tts() -> bool:
    return probe_health("http://127.0.0.1:7891/health")


def probe_health(url: str) -> bool:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            return 200 <= int(response.status) < 300
    except urllib.error.URLError:
        return False


def run_download_stub() -> str:
    script = Path(__file__).resolve().parents[1] / "scripts" / "download-model.py"
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(script)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = (result.stdout + result.stderr).strip()
    return output or "model download not implemented yet - using WSL fallback or halting wizard"


def make_stt(cfg: config_module.Config) -> STTEngine:
    raw = cfg.data["stt"]
    model_dir = raw.get("model_dir")
    return STTEngine(
        STTConfig(
            route=str(raw.get("route", "local")),
            wsl_url=str(raw.get("wsl_url", "http://127.0.0.1:7892")),
            model_dir=Path(model_dir) if model_dir else None,
        )
    )


def validate_hotkey_choice(choice: HotkeyChoice, accept_unregistered: bool = False) -> tuple[bool, str]:
    if choice.vk is None:
        return False, "Choose a hotkey before continuing."
    if accept_unregistered:
        return True, "Hotkey accepted for dry wizard."
    try:
        listener = HotkeyListener(HotkeySpec(vk=choice.vk, modifiers=choice.modifiers), lambda: None, lambda: None)
        listener.start()
        listener.stop()
    except Exception as exc:  # noqa: BLE001
        return False, f"Hotkey is unavailable: {exc}"
    return True, "Hotkey available."


def modifiers_from_qt(modifiers: object) -> list[str]:
    out: list[str] = []
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        out.append("ctrl")
    if modifiers & Qt.KeyboardModifier.AltModifier:
        out.append("alt")
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        out.append("shift")
    if modifiers & Qt.KeyboardModifier.MetaModifier:
        out.append("win")
    return out


def qt_key_to_vk(key: int) -> int:
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return int(key)
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return int(key)
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        return 0x70 + int(key - Qt.Key.Key_F1)
    return int(key)


def describe_hotkey_choice(choice: HotkeyChoice) -> str:
    if choice.vk is None:
        return "No hotkey selected"
    parts = [modifier.upper() for modifier in choice.modifiers]
    parts.append(f"VK 0x{choice.vk:02X}")
    return "+".join(parts)


def phrase_matches_expected(text: str) -> bool:
    expected = normalize_phrase(EXPECTED_TEST_PHRASE)
    actual = normalize_phrase(text)
    return all(token in actual for token in expected.split())


def normalize_phrase(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"[^\w\u4e00-\u9fff ]+", "", text).strip()


def has_wsl_claude_projects_hint() -> bool:
    try:
        return vocab.has_wsl_claude_projects()
    except Exception:
        candidates = [
            Path.home() / ".claude" / "projects",
            Path("/mnt/wsl") / ".claude" / "projects",
        ]
        return any(path.exists() for path in candidates)
