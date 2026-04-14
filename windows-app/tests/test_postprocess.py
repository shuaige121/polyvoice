from __future__ import annotations

import json

from polyvoice_app import postprocess
from polyvoice_app import secrets


def test_apply_hotwords_uses_aliases_and_boundaries():
    out = postprocess.apply_hotwords(
        "请打开 poly voice 和 cosy voice 3, notpoly voice",
        ["polyvoice", "CosyVoice3"],
        {"polyvoice": ("poly voice",)},
    )

    assert out == "请打开 polyvoice 和 CosyVoice3, notpoly voice"


def test_process_text_loads_hotwords_and_master_aliases(tmp_path):
    hotwords = tmp_path / "hotwords.txt"
    master = tmp_path / "master.jsonl"
    hotwords.write_text("PowerShell\npolyvoice\n", encoding="utf-8")
    master.write_text(
        json.dumps({"phrase": "polyvoice", "aliases": ["poly voice"]}) + "\n",
        encoding="utf-8",
    )

    assert postprocess.process_text("open power shell and poly voice", hotwords, master) == (
        "open PowerShell and polyvoice"
    )


def test_secret_denylist_ported():
    assert secrets.is_secret("sk-abcdefghijklmnopqrstuvwxyz")
    assert secrets.redact("email leonard@example.com") == "email [REDACTED]"
