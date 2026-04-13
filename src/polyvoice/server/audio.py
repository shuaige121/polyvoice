"""Audio byte helpers."""

from __future__ import annotations

import base64
import struct


def streaming_wav_header(sample_rate: int, channels: int = 1, bits: int = 16) -> bytes:
    """Return a WAV header for unknown-length PCM streaming."""
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    return (
        b"RIFF"
        + struct.pack("<I", 0xFFFFFFFF)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits)
        + b"data"
        + struct.pack("<I", 0xFFFFFFFF)
    )


def pcm_to_b64(pcm: bytes) -> str:
    return base64.b64encode(pcm).decode("ascii")


def b64_to_pcm(payload: str) -> bytes:
    return base64.b64decode(payload.encode("ascii"), validate=True)
