from __future__ import annotations

from polyvoice_app.dictation_controller import DictationController
from polyvoice_app.paste import PasteResult


class FakeRecorder:
    max_recording_s = 1

    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop_bytes(self) -> bytes:
        return b"\x00\x00"


class FakeSTT:
    def transcribe(self, pcm_bytes: bytes, sr: int = 16000) -> str:
        assert pcm_bytes == b"\x00\x00"
        assert sr == 16000
        return "poly voice"


def test_controller_full_success_pipeline():
    pasted: list[str] = []
    changes: list[tuple[str, str, str]] = []
    controller = DictationController(
        recorder=FakeRecorder(),
        stt=FakeSTT(),
        paste=lambda text: pasted.append(text) or PasteResult(True),
        postprocessor=lambda text: "polyvoice" if text == "poly voice" else text,
        error_reset_s=0.01,
    )
    controller.add_state_callback(lambda change: changes.append((change.old, change.new, change.event)))

    controller.hotkey_press()
    controller.hotkey_release()

    assert controller.wait_idle(timeout=1)
    assert pasted == ["polyvoice"]
    assert changes == [
        ("idle", "recording", "hotkey_press"),
        ("recording", "transcribing", "hotkey_release"),
        ("transcribing", "pasting", "transcribe_done"),
        ("pasting", "idle", "paste_done"),
    ]


def test_controller_error_branch_resets_to_idle():
    controller = DictationController(
        recorder=FakeRecorder(),
        stt=FakeSTT(),
        paste=lambda text: PasteResult(False, "no focused window"),
        error_reset_s=0.01,
    )

    controller.hotkey_press()
    controller.hotkey_release()

    assert controller.wait_idle(timeout=1)
    assert controller.last_error == "no focused window"


def test_controller_ignores_release_when_idle():
    changes: list[tuple[str, str, str]] = []
    controller = DictationController(
        recorder=FakeRecorder(),
        stt=FakeSTT(),
        paste=lambda text: PasteResult(True),
        error_reset_s=0.01,
    )
    controller.add_state_callback(lambda change: changes.append((change.old, change.new, change.event)))

    controller.hotkey_release()

    assert controller.state == "idle"
    assert changes == []
