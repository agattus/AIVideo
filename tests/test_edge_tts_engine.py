from __future__ import annotations

from pathlib import Path

import pytest

from youtube_pipeline.audio.tts import AudioEngine
from youtube_pipeline.models import SceneData, VideoScript


def test_edge_tts_routing_writes_voiceover(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from config.settings import Settings, TTSProvider

    settings = Settings(
        tts_provider=TTSProvider.EDGE_TTS,
        edge_tts_voice="en-US-ChristopherNeural",
        openai_api_key="unused",
    )

    # Bypass package-import check in __init__.
    monkeypatch.setattr(AudioEngine, "_validate_config", lambda self: None)
    engine = AudioEngine(settings)

    class _FakeCommunicate:
        def __init__(self, text: str, voice: str) -> None:
            self.text = text
            self.voice = voice

        async def save(self, path: str) -> None:
            Path(path).write_bytes(b"ID3fake-edge-tts")

    import types
    import sys

    fake_mod = types.ModuleType("edge_tts")
    fake_mod.Communicate = _FakeCommunicate  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "edge_tts", fake_mod)

    # Avoid moviepy probing a fake mp3.
    monkeypatch.setattr(engine, "_probe_duration_seconds", lambda path: 2.0)

    script = VideoScript(
        title="Edge",
        full_script="Hello from edge tts.",
        style="cinematic",
        scenes=[
            SceneData(
                scene_id=0,
                script_text="Hello from edge tts.",
                visual_prompt="A friendly narrator",
                keywords=["voice"],
            )
        ],
    )
    result = engine.synthesize(script, tmp_path / "audio")
    assert result.audio_path.exists()
    assert result.audio_path.read_bytes() == b"ID3fake-edge-tts"
    assert result.duration_seconds == 2.0
    assert result.script.scenes[0].duration > 0
