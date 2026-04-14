"""SenseVoice sherpa-onnx backend adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from polyvoice.backends.stt.base import Transcript


class SenseVoiceBackend:
    name = "sensevoice"

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self.options = options or {}
        self.model_path = Path(self.options.get("model_path", "models/SenseVoiceSmall-onnx-fp16"))
        self.hotwords_file = Path(self.options.get("hotwords_file", "vocab/adapters/sensevoice.txt"))
        self._recognizer = None
        self._hotwords_mtime: float | None = None
        self._load()

    def transcribe(
        self,
        pcm: bytes,
        sample_rate: int,
        hotwords: list[str] | None = None,
        language: str | None = None,
    ) -> Transcript:
        del hotwords
        if sample_rate != 16000:
            raise ValueError("sensevoice worker expects 16kHz PCM")
        self._reload_hotwords_if_needed()
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        stream = self._recognizer.create_stream()  # type: ignore[union-attr]
        stream.accept_waveform(16000, samples)
        self._recognizer.decode_stream(stream)  # type: ignore[union-attr]
        text = getattr(stream.result, "text", "") if hasattr(stream, "result") else ""
        return Transcript(text=text, language=language or "auto", segments=[])

    def _load(self) -> None:
        try:
            import sherpa_onnx
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("sherpa-onnx is not installed; run scripts/setup-venvs.sh") from exc
        if not self.model_path.exists():
            raise RuntimeError(f"SenseVoice model path missing: {self.model_path}")
        # TODO(spec): ruska1117/SenseVoiceSmall-onnx-fp16 file names are not
        # specified in SPEC; infer common sherpa-onnx names when present.
        model = next(self.model_path.glob("*.onnx"), None)
        tokens = next(self.model_path.glob("*tokens*.txt"), None) or next(
            self.model_path.glob("*tokens*.json"), None
        )
        if model is None or tokens is None:
            raise RuntimeError(f"SenseVoice model files not found under {self.model_path}")
        # NOTE: sherpa-onnx 1.10+ from_sense_voice does NOT expose hotwords_file
        # (CTC topology, not transducer). Bias requires hr_dict_dir / hr_rule_fsts
        # (FST homophone replacement) or post-processing. Tracked as follow-up.
        # Prefer the model.int8.onnx file when available (smaller + faster).
        preferred = self.model_path / "model.int8.onnx"
        chosen_model = preferred if preferred.exists() else model
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(chosen_model),
            tokens=str(tokens),
            num_threads=int(self.options.get("num_threads", 4)),
            provider=str(self.options.get("device", "cpu")),
            use_itn=bool(self.options.get("use_itn", True)),
        )
        self._hotwords_mtime = self.hotwords_file.stat().st_mtime if self.hotwords_file.exists() else None

    def _reload_hotwords_if_needed(self) -> None:
        mtime = self.hotwords_file.stat().st_mtime if self.hotwords_file.exists() else None
        if mtime != self._hotwords_mtime:
            self._load()
