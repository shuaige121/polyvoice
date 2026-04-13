"""CosyVoice3 zero-shot backend adapter."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from polyvoice.config import ROOT


class CosyVoice3Backend:
    name = "cosyvoice3"
    sample_rate = 24000

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self.options = options or {}
        self.voices_dir = Path(self.options.get("voices_dir", ROOT / "assets/voices")).expanduser()
        self.model_path = Path(self.options.get("model_path", ROOT / "models/Fun-CosyVoice3-0.5B-2512"))
        self._engine = None
        self._load_engine()

    def list_voices(self) -> list[str]:
        voices = sorted(path.stem for path in self.voices_dir.glob("*.wav") if path.with_suffix(".txt").exists())
        fallback = ROOT / "assets/voices"
        voices.extend(path.stem for path in fallback.glob("*.wav") if path.with_suffix(".txt").exists())
        return sorted(set(voices))

    def stream(self, text: str, voice: str, speed: float = 1.0) -> Iterator[bytes]:
        wav, prompt_text = self._voice_pair(voice)
        for item in self._engine.inference_zero_shot(  # type: ignore[union-attr]
            text,
            prompt_text,
            str(wav),
            stream=True,
            speed=speed,
        ):
            tensor = item["tts_speech"] if isinstance(item, dict) else item
            data = tensor.detach().cpu().numpy().reshape(-1)
            clipped = np.clip(data, -1.0, 1.0)
            yield (clipped * 32767.0).astype("<i2").tobytes()

    def _voice_pair(self, voice: str) -> tuple[Path, str]:
        for base in (self.voices_dir, ROOT / "assets/voices"):
            wav = base / f"{voice}.wav"
            text = wav.with_suffix(".txt")
            if wav.exists() and text.exists():
                # TODO(spec): Current upstream CosyVoice3 requires <|endofprompt|>
                # in prompt_text, while SPEC lists the older CosyVoice prompt text.
                return wav, text.read_text(encoding="utf-8").strip()
        raise ValueError(f"unknown voice: {voice}")

    def _load_engine(self) -> None:
        if bool(self.options.get("force_cpu", False)):
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
        else:
            # Force CUDA context init before transformers/triton imports.
            # Without this, triton 3.3+ on WSL2 + Blackwell raises
            # "0 active drivers ([])" during transformers.modeling_utils import.
            import torch  # noqa: PLC0415

            if torch.cuda.is_available():
                torch.cuda.init()
        third_party = ROOT / "third_party/CosyVoice"
        if third_party.exists():
            sys.path.insert(0, str(third_party))
            sys.path.insert(0, str(third_party / "third_party/Matcha-TTS"))
        try:
            from cosyvoice.cli.cosyvoice import CosyVoice3
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "CosyVoice3 import failed; run scripts/setup-venvs.sh and scripts/download-models.sh"
            ) from exc
        if not self.model_path.exists():
            raise RuntimeError(f"CosyVoice3 model path missing: {self.model_path}")
        self._engine = CosyVoice3(
            str(self.model_path),
            load_trt=False,
            load_vllm=False,
            fp16=bool(self.options.get("fp16", True)),
        )
