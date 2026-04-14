from __future__ import annotations

import pytest

from polyvoice_app.hotkey import HotkeyError, HotkeySpec, parse_modifiers


def test_modifier_flags():
    assert parse_modifiers(["alt", "shift"]) == 0x0001 | 0x0004


def test_unknown_modifier_rejected():
    with pytest.raises(HotkeyError):
        HotkeySpec(vk=0x70, modifiers=("hyper",)).modifier_flags
