"""Claude Code Stop hook installer for WSL homes."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from polyvoice_app import config as config_module
from polyvoice_app import vocab
from polyvoice_app.tts_client import health_check

logger = logging.getLogger("polyvoice.hook_installer")

HOOK_ID = "polyvoice-windows-stop-tts"
SCRIPT_NAME = "polyvoice_stop_hook.py"


@dataclass(frozen=True)
class HookTarget:
    distro: str
    user: str
    claude_dir: Path
    settings_path: Path
    script_path: Path


@dataclass(frozen=True)
class HookInstallResult:
    installed: bool
    target: HookTarget | None
    message: str


def default_target(distro: str | None = None, user: str | None = None) -> HookTarget | None:
    distros = [distro] if distro else vocab.enumerate_wsl_distros()
    for name in distros:
        for root in vocab.find_claude_project_roots(name):
            if user and root.user != user:
                continue
            claude_dir = root.path.parent
            return HookTarget(
                distro=root.distro,
                user=root.user,
                claude_dir=claude_dir,
                settings_path=claude_dir / "settings.json",
                script_path=claude_dir / SCRIPT_NAME,
            )
    return None


def install_hook(
    cfg: config_module.Config,
    *,
    distro: str | None = None,
    user: str | None = None,
) -> HookInstallResult:
    target = default_target(distro=distro, user=user)
    if target is None:
        return HookInstallResult(False, None, "No WSL Claude Code settings path found.")
    tts_url = str(cfg.data["tts"].get("url", "http://127.0.0.1:7891"))
    voice = str(cfg.data["tts"].get("voice", "f1"))
    if bool(cfg.data["tts"].get("enabled")) and health_check(tts_url):
        endpoint = tts_url.rstrip("/") + "/v1/audio/speech"
    else:
        endpoint = "http://127.0.0.1:7893/speak"
    _write_hook_script(target.script_path, endpoint=endpoint, voice=voice)
    settings = _read_settings(target.settings_path)
    merged = merge_stop_hook(settings, _hook_entry(target.script_path))
    _atomic_write_json(target.settings_path, merged)
    cfg.data["hook_installed"] = True
    config_module.save_config(cfg)
    return HookInstallResult(True, target, f"Installed Stop hook for {target.distro}:{target.user}.")


def uninstall_hook(
    cfg: config_module.Config,
    *,
    distro: str | None = None,
    user: str | None = None,
) -> HookInstallResult:
    target = default_target(distro=distro, user=user)
    if target is None:
        cfg.data["hook_installed"] = False
        config_module.save_config(cfg)
        return HookInstallResult(False, None, "No WSL Claude Code settings path found.")
    settings = _read_settings(target.settings_path)
    updated = remove_stop_hook(settings)
    _atomic_write_json(target.settings_path, updated)
    try:
        target.script_path.unlink()
    except FileNotFoundError:
        pass
    cfg.data["hook_installed"] = False
    config_module.save_config(cfg)
    return HookInstallResult(False, target, f"Removed Stop hook for {target.distro}:{target.user}.")


def merge_stop_hook(settings: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    merged = dict(settings)
    hooks = dict(merged.get("hooks", {})) if isinstance(merged.get("hooks"), dict) else {}
    stop_hooks = hooks.get("Stop", [])
    if not isinstance(stop_hooks, list):
        stop_hooks = []
    stop_hooks = [item for item in stop_hooks if not _is_polyvoice_entry(item)]
    stop_hooks.append(entry)
    hooks["Stop"] = stop_hooks
    merged["hooks"] = hooks
    return merged


def remove_stop_hook(settings: dict[str, Any]) -> dict[str, Any]:
    merged = dict(settings)
    hooks = dict(merged.get("hooks", {})) if isinstance(merged.get("hooks"), dict) else {}
    stop_hooks = hooks.get("Stop", [])
    if isinstance(stop_hooks, list):
        hooks["Stop"] = [item for item in stop_hooks if not _is_polyvoice_entry(item)]
    merged["hooks"] = hooks
    return merged


def _hook_entry(script_path: Path) -> dict[str, Any]:
    return {
        "matcher": "",
        "hooks": [
            {
                "type": "command",
                "command": f"python3 ~/.claude/{SCRIPT_NAME}",
                "description": HOOK_ID,
            }
        ],
    }


def _is_polyvoice_entry(item: Any) -> bool:
    return HOOK_ID in json.dumps(item, ensure_ascii=False) or SCRIPT_NAME in json.dumps(item, ensure_ascii=False)


def _read_settings(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Claude Code settings.json is not valid JSON: {path}") from exc


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _write_hook_script(path: Path, *, endpoint: str, voice: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    script = HOOK_SCRIPT_TEMPLATE.replace("__ENDPOINT__", endpoint).replace("__VOICE__", voice)
    path.write_text(script, encoding="utf-8")
    try:
        path.chmod(0o755)
    except OSError:
        logger.debug("hook script chmod failed", exc_info=True)


HOOK_SCRIPT_TEMPLATE = r'''#!/usr/bin/env python3
import json
import re
import sys
import urllib.request

ENDPOINT = "__ENDPOINT__"
VOICE = "__VOICE__"

CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE = re.compile(r"`([^`]+)`")
MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
MARKDOWN = re.compile(r"[*_#>\-]+")
WHITESPACE = re.compile(r"\s+")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        return 0
    text = last_assistant_message(transcript_path)
    text = strip_markdown(text)
    if not text:
        return 0
    body = json.dumps(
        {"input": text, "text": text, "voice": VOICE, "response_format": "wav"},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            while response.read(65536):
                pass
    except Exception:
        return 0
    return 0


def last_assistant_message(path: str) -> str:
    last = ""
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = row.get("message", row)
                if not isinstance(message, dict) or message.get("role") != "assistant":
                    continue
                text = content_to_text(message.get("content"))
                if text:
                    last = text
    except OSError:
        return ""
    return last


def content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts)
    return ""


def strip_markdown(text: str) -> str:
    text = CODE_BLOCK.sub(" ", text)
    text = INLINE_CODE.sub(r"\1", text)
    text = MARKDOWN_LINK.sub(r"\1", text)
    text = MARKDOWN.sub(" ", text)
    return WHITESPACE.sub(" ", text).strip()[:4000]


if __name__ == "__main__":
    raise SystemExit(main())
'''
