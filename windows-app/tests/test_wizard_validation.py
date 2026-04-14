from __future__ import annotations

import os

import pytest

if os.environ.get("PYVOICE_SKIP_GUI_TESTS") == "1":
    pytest.skip("GUI validation tests skipped by PYVOICE_SKIP_GUI_TESTS=1", allow_module_level=True)

pytest.importorskip("PySide6")

from polyvoice_app.wizard import (  # noqa: E402
    HotkeyChoice,
    normalize_phrase,
    phrase_matches_expected,
    validate_hotkey_choice,
)


def test_dry_hotkey_validation_requires_explicit_key():
    ok, message = validate_hotkey_choice(HotkeyChoice(None), accept_unregistered=True)

    assert not ok
    assert "Choose a hotkey" in message


def test_dry_hotkey_validation_accepts_chosen_key():
    ok, message = validate_hotkey_choice(HotkeyChoice(0x41, ("ctrl", "shift")), accept_unregistered=True)

    assert ok
    assert "accepted" in message


def test_finish_phrase_loose_match():
    assert phrase_matches_expected("你好, PolyVoice, 测试一下!")
    assert not phrase_matches_expected("hello polyvoice")
    assert normalize_phrase("PolyVoice!!!") == "polyvoice"
