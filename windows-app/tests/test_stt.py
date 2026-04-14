from __future__ import annotations

from polyvoice_app.stt import STTConfig, STTEngine, STTNotReadyError, model_missing_message


def test_local_stt_missing_model_raises(tmp_path):
    engine = STTEngine(STTConfig(model_dir=tmp_path / "missing"))

    try:
        engine.transcribe(b"\x00\x00")
    except STTNotReadyError as exc:
        assert "scripts/download-model.py" in str(exc)
    else:
        raise AssertionError("expected STTNotReadyError")


def test_model_missing_message_points_to_int8_model(tmp_path):
    message = model_missing_message(tmp_path)

    assert "model.int8.onnx" in message
    assert "tokens.txt" in message
