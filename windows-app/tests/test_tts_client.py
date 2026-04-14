from __future__ import annotations

import io
import json
import struct
from typing import Any

from polyvoice_app import config
from polyvoice_app.tts_client import TTSClient, parse_wav_header


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class FakeStream:
    writes: list[Any] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def write(self, data):
        self.writes.append(data.copy())

    def abort(self):
        return None


def test_parse_wav_header_accepts_pcm16():
    info = parse_wav_header(_wav_bytes()[0:44])

    assert info.sample_rate == 24000
    assert info.channels == 1
    assert info.dtype == "int16"


def test_tts_client_posts_json_and_plays_stream(tmp_path, monkeypatch):
    cfg = config.Config(config.default_settings(), tmp_path / "settings.json")
    requests = []
    FakeStream.writes = []

    def fake_urlopen(request, timeout):
        del timeout
        requests.append(request)
        return FakeResponse(_wav_bytes())

    monkeypatch.setattr("polyvoice_app.tts_client.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("polyvoice_app.tts_client.sd.OutputStream", FakeStream)

    result = TTSClient(cfg).speak_blocking("测试")

    assert result.ok
    body = json.loads(requests[0].data.decode("utf-8"))
    assert body == {"input": "测试", "voice": "f1", "response_format": "wav"}
    assert requests[0].full_url == "http://127.0.0.1:7891/v1/audio/speech"
    assert FakeStream.writes


def _wav_bytes() -> bytes:
    pcm = struct.pack("<hhhh", 0, 100, -100, 0)
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 24000, 24000 * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(pcm))
    )
    return header + pcm
