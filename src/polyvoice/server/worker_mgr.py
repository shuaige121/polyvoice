"""JSON-lines subprocess worker lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
import json
import signal
import sys
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from polyvoice.config import ROOT
from polyvoice.logging import log


class WorkerError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerSpec:
    kind: str
    backend: str
    options: dict[str, Any]


class JsonLineWorker:
    def __init__(self, spec: WorkerSpec) -> None:
        self.spec = spec
        self.process: asyncio.subprocess.Process | None = None
        self.sample_rate = 0
        self.started_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        return self.process is not None and self.process.returncode is None and self.sample_rate > 0

    async def start(self) -> None:
        await self.stop()
        cmd = self._command()
        log("worker_start", kind=self.spec.kind, backend=self.spec.backend, cmd=cmd)
        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=None,
            cwd=ROOT,
            limit=10 * 1024 * 1024,
        )
        self.started_at = time.monotonic()
        ready = await self._read_json(timeout=180.0)
        if not ready.get("ready"):
            raise WorkerError(f"worker failed readiness: {ready}")
        self.sample_rate = int(ready.get("sample_rate", 0))

    async def stop(self) -> None:
        proc = self.process
        if proc is None:
            return
        if proc.returncode is None:
            try:
                await self.request("shutdown")
            except Exception as exc:  # noqa: BLE001
                log("worker_shutdown_request_failed", error=str(exc))
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.send_signal(signal.SIGTERM)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
        self.process = None
        self.sample_rate = 0

    async def request(self, op: str, **payload: Any) -> dict[str, Any]:
        async with self._lock:
            request_id = f"req-{uuid.uuid4().hex}"
            await self._write({"id": request_id, "op": op, **payload})
            while True:
                frame = await self._read_json()
                if frame.get("id") != request_id:
                    raise WorkerError(f"unexpected worker frame: {frame}")
                if frame.get("ok") is False:
                    raise WorkerError(str(frame.get("error", "worker error")))
                return dict(frame.get("result", {}))

    async def stream(self, op: str, **payload: Any) -> AsyncIterator[dict[str, Any]]:
        async with self._lock:
            request_id = f"req-{uuid.uuid4().hex}"
            await self._write({"id": request_id, "op": op, **payload})
            while True:
                frame = await self._read_json()
                if frame.get("id") != request_id:
                    raise WorkerError(f"unexpected worker frame: {frame}")
                if frame.get("ok") is False:
                    raise WorkerError(str(frame.get("error", "worker error")))
                yield frame
                if frame.get("done"):
                    return

    def _command(self) -> list[str]:
        venv = self.spec.options.get("venv")
        python = Path(venv) / "bin" / "python" if venv else None
        exe = str(python) if python and python.exists() else sys.executable
        module = f"polyvoice.backends.{self.spec.kind}.worker_entry"
        return [exe, "-m", module, self.spec.backend, json.dumps(self.spec.options, default=str)]

    async def _write(self, payload: dict[str, Any]) -> None:
        proc = self.process
        if proc is None or proc.stdin is None or proc.returncode is not None:
            raise WorkerError("worker not ready")
        proc.stdin.write(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
        await proc.stdin.drain()

    async def _read_json(self, timeout: float | None = None) -> dict[str, Any]:
        proc = self.process
        if proc is None or proc.stdout is None:
            raise WorkerError("worker not ready")
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise WorkerError("worker read timed out") from exc
        if not line:
            raise WorkerError(f"worker exited with code {proc.returncode}")
        text = line.decode("utf-8")
        with contextlib.suppress(json.JSONDecodeError):
            return json.loads(text)
        log("worker_stdout_non_protocol", line=text.strip())
        return await self._read_json(timeout=timeout)
