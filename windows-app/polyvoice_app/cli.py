"""Headless CLI smoke entrypoint for the Windows app pipeline."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from pathlib import Path

from polyvoice_app import config as config_module
from polyvoice_app import logging_setup
from polyvoice_app import paths
from polyvoice_app.dictation_controller import DictationController
from polyvoice_app.hotkey import HotkeyListener, HotkeySpec
from polyvoice_app.paste import paste_text
from polyvoice_app.recorder import MicSelection, Recorder, list_microphones
from polyvoice_app.stt import STTConfig, STTEngine, model_missing_message

logger = logging.getLogger("polyvoice.cli")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="polyvoice Windows app CLI smoke mode")
    parser.add_argument("--probe", action="store_true", help="print microphone, model, and hotkey status")
    parser.add_argument("--hotkey-test-s", type=float, default=5, help="seconds to wait for hotkey in probe")
    args = parser.parse_args(argv)

    cfg = config_module.load_config()
    logging_setup.setup_logging(str(cfg.data.get("log_level", "INFO")))
    logger.info("cli started", extra={"event": "cli_started", "probe": args.probe})

    if args.probe:
        return probe(cfg, hotkey_test_s=args.hotkey_test_s)
    return run_pipeline(cfg)


def probe(cfg: config_module.Config, hotkey_test_s: float = 5) -> int:
    print("polyvoice probe")
    print(f"config: {cfg.path}")
    print(f"logs: {paths.log_path()}")
    print()
    print("Microphones:")
    try:
        microphones = list_microphones()
    except Exception as exc:  # noqa: BLE001
        print(f"  unavailable: {exc}")
    else:
        if not microphones:
            print("  no input devices detected")
        for mic in microphones:
            print(
                "  "
                f"[{mic['index']}] {mic['name']} "
                f"({mic['channels']} ch, default {mic['default_samplerate']} Hz)"
            )
    print()

    stt = _make_stt(cfg)
    if cfg.data["stt"].get("route") == "local":
        if stt.model_ready():
            print(f"STT model: ready at {stt.model_dir}")
        else:
            print(f"STT model: missing. {model_missing_message(stt.model_dir)}")
    else:
        print(f"STT route: WSL at {cfg.data['stt'].get('wsl_url')}")
    print()

    print(
        "Hotkey test: "
        f"press {describe_hotkey(cfg)} within {hotkey_test_s:g}s "
        "(RegisterHotKey + GetAsyncKeyState)."
    )
    result = _probe_hotkey(cfg, hotkey_test_s)
    print(f"  {result}")
    return 0


def run_pipeline(cfg: config_module.Config) -> int:
    recorder = Recorder(
        MicSelection(
            name=cfg.data["mic"].get("name"),
            index=cfg.data["mic"].get("index"),
        ),
        max_recording_s=cfg.max_recording_s,
    )
    controller = DictationController(
        recorder=recorder,
        stt=_make_stt(cfg),
        paste=paste_text,
    )
    controller.add_state_callback(
        lambda change: print(f"state: {change.old} -> {change.new} ({change.event})", flush=True)
    )
    listener = HotkeyListener(
        _hotkey_spec(cfg),
        on_press=controller.hotkey_press,
        on_release=controller.hotkey_release,
    )
    stop = threading.Event()

    def handle_signal(signum: int, frame: object) -> None:
        del signum, frame
        stop.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print(f"polyvoice CLI ready. Hold {describe_hotkey(cfg)} to dictate. Ctrl+C to quit.")
    try:
        listener.start()
    except Exception as exc:  # noqa: BLE001
        logger.exception("hotkey start failed", extra={"event": "hotkey_start_failed", "error": str(exc)})
        print(f"Hotkey unavailable: {exc}", file=sys.stderr)
        return 2

    try:
        while not stop.is_set():
            time.sleep(0.2)
    finally:
        listener.stop()
    return 0


def describe_hotkey(cfg: config_module.Config) -> str:
    modifiers = "+".join(m.upper() for m in cfg.hotkey_modifiers)
    key = f"VK 0x{cfg.hotkey_vk:02X}"
    return f"{modifiers}+{key}" if modifiers else key


def _probe_hotkey(cfg: config_module.Config, hotkey_test_s: float) -> str:
    pressed = threading.Event()
    released = threading.Event()
    listener = HotkeyListener(
        _hotkey_spec(cfg),
        on_press=pressed.set,
        on_release=released.set,
    )
    try:
        listener.start()
    except Exception as exc:  # noqa: BLE001
        return f"unavailable: {exc}"
    try:
        if not pressed.wait(timeout=hotkey_test_s):
            return "registered, no press observed"
        if released.wait(timeout=max(1.0, hotkey_test_s)):
            return "press and release observed"
        return "press observed, release not observed"
    finally:
        listener.stop()


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
    return HotkeySpec(
        vk=cfg.hotkey_vk,
        modifiers=tuple(cfg.hotkey_modifiers),
        toggle=cfg.hotkey_toggle,
    )


if __name__ == "__main__":
    raise SystemExit(main())
