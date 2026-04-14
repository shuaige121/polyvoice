"""OpenAI-compatible STT HTTP server."""

from __future__ import annotations

import subprocess
import time
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from polyvoice.config import Config, load_config
from polyvoice.server.audio import pcm_to_b64
from polyvoice.server.worker_mgr import JsonLineWorker, WorkerError, WorkerSpec


class STTState:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.backend = config.stt.backend
        self.worker: JsonLineWorker | None = None
        self.started_at = time.monotonic()

    async def start(self) -> None:
        options = dict(self.config.stt.backends.get(self.backend, {}))
        options["hotwords_file"] = str(self.config.stt.hotwords_file)
        self.worker = JsonLineWorker(WorkerSpec(kind="stt", backend=self.backend, options=options))
        await self.worker.start()

    async def stop(self) -> None:
        if self.worker:
            await self.worker.stop()

    def require_worker(self) -> JsonLineWorker:
        if not self.worker or not self.worker.ready:
            raise HTTPException(status_code=503, detail="worker not ready")
        return self.worker


def decode_audio_to_pcm(audio: bytes) -> tuple[bytes, int]:
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            "16000",
            "pipe:1",
        ],
        input=audio,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError(proc.stderr.decode("utf-8", errors="replace"))
    return proc.stdout, 16000


def _split_hotwords(header_value: str | None, form_value: str | None) -> list[str]:
    raw = form_value or header_value or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


def create_app(config: Config | None = None) -> FastAPI:
    state = STTState(config or load_config())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.stt = state
        await state.start()
        try:
            yield
        finally:
            await state.stop()

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        worker = state.worker
        return {
            "ok": bool(worker and worker.ready),
            "backend": state.backend,
            "uptime_s": round(time.monotonic() - state.started_at, 3),
        }

    @app.post("/v1/audio/transcriptions")
    async def transcribe(
        file: UploadFile = File(),
        model: str = Form("sensevoice"),
        language: str = Form("auto"),
        response_format: str = Form("json"),
        x_hotwords: str | None = Form(None),
    ):
        del model
        raw = await file.read()
        try:
            pcm, sample_rate = decode_audio_to_pcm(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        hotwords = _split_hotwords(None, x_hotwords)
        worker = state.require_worker()
        try:
            result = await worker.request(
                "transcribe",
                pcm_b64=pcm_to_b64(pcm),
                sr=sample_rate,
                hotwords=hotwords,
                language=language,
            )
        except WorkerError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        # Post-process: SenseVoice has no native hotword biasing, so we apply
        # variant-based substitution against the configured hotwords file.
        from polyvoice.vocab.postprocess import (
            apply_hotwords,
            load_hotwords,
            load_master_aliases,
        )

        configured = [phrase for phrase, _ in load_hotwords(state.config.stt.hotwords_file)]
        merged = list(dict.fromkeys(configured + hotwords))
        if merged:
            master_path = state.config.stt.hotwords_file.parent.parent / "master.jsonl"
            aliases_map = load_master_aliases(master_path)
            text_in = str(result.get("text", ""))
            result["text"] = apply_hotwords(text_in, merged, aliases_map)
        if response_format == "text":
            return PlainTextResponse(str(result.get("text", "")))
        if response_format != "json":
            raise HTTPException(status_code=400, detail="response_format must be json or text")
        return result

    return app


def main() -> None:
    config = load_config()
    import os  # noqa: PLC0415
    host = os.environ.get("POLYVOICE_HOST", "0.0.0.0")
    uvicorn.run(create_app(config), host=host, port=config.stt.port)


if __name__ == "__main__":
    main()
