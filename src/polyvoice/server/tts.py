"""OpenAI-compatible TTS HTTP server."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from polyvoice.config import Config, load_config
from polyvoice.logging import log
from polyvoice.server.audio import b64_to_pcm, streaming_wav_header
from polyvoice.server.worker_mgr import JsonLineWorker, WorkerError, WorkerSpec


class SpeechRequest(BaseModel):
    model: str = "cosyvoice3"
    input: str = Field(min_length=1)
    voice: str | None = None
    response_format: str = "wav"
    speed: float = 1.0


class SwitchRequest(BaseModel):
    backend: str


class TTSState:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.backend = config.tts.backend
        self.worker: JsonLineWorker | None = None
        self.started_at = time.monotonic()
        self.voices: set[str] = set()

    async def start(self) -> None:
        try:
            await self.switch(self.backend)
        except Exception as exc:  # noqa: BLE001
            if self.backend != "edge_tts":
                log("tts_primary_failed_fallback_edge", backend=self.backend, error=str(exc))
                await self.switch("edge_tts")
            else:
                raise

    async def stop(self) -> None:
        if self.worker:
            await self.worker.stop()

    async def switch(self, backend: str) -> None:
        options = dict(self.config.tts.backends.get(backend, {}))
        worker = JsonLineWorker(WorkerSpec(kind="tts", backend=backend, options=options))
        await worker.start()
        result = await worker.request("list_voices")
        voices = set(result.get("voices", []))
        old = self.worker
        self.worker = worker
        self.backend = backend
        self.voices = voices
        if old:
            await old.stop()

    def require_worker(self) -> JsonLineWorker:
        if not self.worker or not self.worker.ready:
            raise HTTPException(status_code=503, detail="worker not ready")
        return self.worker


def create_app(config: Config | None = None) -> FastAPI:
    state = TTSState(config or load_config())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.tts = state
        await state.start()
        try:
            yield
        finally:
            await state.stop()

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        worker = state.worker
        ok = bool(worker and worker.ready)
        return {
            "ok": ok,
            "backend": state.backend,
            "sample_rate": worker.sample_rate if worker else 0,
            "uptime_s": round(time.monotonic() - state.started_at, 3),
        }

    @app.get("/v1/audio/voices")
    async def voices() -> dict[str, list[str]]:
        state.require_worker()
        return {"voices": sorted(state.voices)}

    @app.post("/admin/switch")
    async def switch(req: SwitchRequest) -> dict[str, Any]:
        try:
            await state.switch(req.backend)
        except WorkerError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"backend": state.backend}

    @app.post("/v1/audio/speech")
    async def speech(req: SpeechRequest) -> StreamingResponse:
        if req.response_format != "wav":
            raise HTTPException(status_code=400, detail="only wav response_format is supported")
        text = req.input.strip()
        if not text:
            raise HTTPException(status_code=400, detail="input must not be empty")
        voice = req.voice or state.config.tts.default_voice
        if voice not in state.voices:
            raise HTTPException(status_code=400, detail=f"unknown voice: {voice}")
        worker = state.require_worker()

        async def body() -> AsyncIterator[bytes]:
            import asyncio  # noqa: PLC0415
            yield streaming_wav_header(worker.sample_rate)
            await asyncio.sleep(0)  # let header flush before waiting on worker
            async for frame in worker.stream("speak", text=text, voice=voice, speed=req.speed):
                if "chunk" in frame:
                    yield b64_to_pcm(str(frame["chunk"]))
                    await asyncio.sleep(0)  # yield each PCM chunk immediately

        return StreamingResponse(body(), media_type="audio/wav")

    @app.exception_handler(WorkerError)
    async def worker_error(_: Any, exc: WorkerError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    return app


def main() -> None:
    config = load_config()
    uvicorn.run(create_app(config), host="127.0.0.1", port=config.tts.port)


if __name__ == "__main__":
    main()
