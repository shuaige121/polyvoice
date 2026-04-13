from polyvoice.server.audio import streaming_wav_header


def test_streaming_wav_header_unknown_size() -> None:
    header = streaming_wav_header(24000)
    assert header[:4] == b"RIFF"
    assert header[4:8] == b"\xff\xff\xff\xff"
    assert header[8:12] == b"WAVE"
    assert header[-8:-4] == b"data"
    assert header[-4:] == b"\xff\xff\xff\xff"
    assert len(header) == 44
