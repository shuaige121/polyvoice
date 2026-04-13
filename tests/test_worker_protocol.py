from polyvoice.backends.tts.edge_tts import EdgeTTSBackend


def test_edge_tts_voice_aliases() -> None:
    backend = EdgeTTSBackend({})
    voices = backend.list_voices()
    assert "f1" in voices
    assert "zh-CN-XiaoxiaoNeural" in voices
