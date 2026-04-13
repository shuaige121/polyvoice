from pathlib import Path

from polyvoice.config import load_config


def test_load_config_expands_repo_relative_paths(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[tts]
backend = "edge_tts"
port = 7891
default_voice = "f1"

[tts.backends.edge_tts]
default_voice = "zh-CN-XiaoxiaoNeural"

[stt]
hotwords_file = "vocab/adapters/sensevoice.txt"
""",
        encoding="utf-8",
    )
    config = load_config(config_file)
    assert config.tts.backend == "edge_tts"
    assert config.tts.port == 7891
    assert config.stt.hotwords_file.is_absolute()
