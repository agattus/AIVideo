from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

from youtube_pipeline.audio.tts import AudioEngine
from youtube_pipeline.models import SceneData, VideoScript


def _patch_edge_tts(monkeypatch: pytest.MonkeyPatch, calls: list | None = None) -> None:
    class _FakeCommunicate:
        def __init__(self, text: str, voice: str, **_kwargs) -> None:
            self.text = text
            self.voice = voice
            if calls is not None:
                calls.append({"text": text, "voice": voice, **_kwargs})

        async def save(self, path: str) -> None:
            Path(path).write_bytes(b"ID3fake-edge-tts")

    fake_mod = types.ModuleType("edge_tts")
    fake_mod.Communicate = _FakeCommunicate  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "edge_tts", fake_mod)


def _sample_script(*, scenes: int = 1) -> VideoScript:
    items = [
        SceneData(
            scene_id=i,
            script_text=f"Line number {i} for the film.",
            visual_prompt=f"Visual {i}",
            keywords=["voice"],
        )
        for i in range(scenes)
    ]
    return VideoScript(
        title="Edge",
        full_script=" ".join(s.script_text for s in items),
        style="cinematic",
        scenes=items,
    )


def _engine(monkeypatch: pytest.MonkeyPatch, **settings_kwargs) -> AudioEngine:
    from config.settings import Settings, TTSProvider

    kwargs = {
        "tts_provider": TTSProvider.EDGE_TTS,
        "edge_tts_voice": "en-US-ChristopherNeural",
        "edge_tts_rate": "-20%",
        "edge_tts_scene_pause_ms": 450,
        "openai_api_key": "unused",
        "_env_file": None,
    }
    kwargs.update(settings_kwargs)
    settings = Settings(**kwargs)
    monkeypatch.setattr(AudioEngine, "_validate_config", lambda self: None)
    return AudioEngine(settings)


def test_normalize_edge_rate_adds_sign_for_unsigned_percent() -> None:
    from youtube_pipeline.audio.tts import normalize_edge_rate

    assert normalize_edge_rate("8%") == "-8%"
    assert normalize_edge_rate("-8%") == "-8%"
    assert normalize_edge_rate("+8%") == "+8%"
    assert normalize_edge_rate("\u22128%") == "-8%"
    assert normalize_edge_rate("") == "-20%"


def test_edge_tts_prosody_accepts_unsigned_rate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []
    engine = _engine(monkeypatch, edge_tts_rate="8%")
    _patch_edge_tts(monkeypatch, calls)
    monkeypatch.setattr(engine, "_probe_duration_seconds", lambda path: 1.5)

    engine.synthesize(_sample_script(), tmp_path / "audio")
    assert calls
    assert calls[0]["rate"] == "-8%"


def test_edge_tts_routing_writes_voiceover(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(monkeypatch)
    _patch_edge_tts(monkeypatch)
    monkeypatch.setattr(engine, "_probe_duration_seconds", lambda path: 2.0)

    result = engine.synthesize(_sample_script(), tmp_path / "audio")
    assert result.audio_path.exists()
    assert result.audio_path.read_bytes() == b"ID3fake-edge-tts"
    assert result.duration_seconds == 2.0
    assert result.script.scenes[0].duration > 0


def test_edge_tts_works_inside_running_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: FastAPI voiceover update is async; nested asyncio.run must not fail."""
    engine = _engine(monkeypatch, edge_tts_voice="en-US-AriaNeural")
    _patch_edge_tts(monkeypatch)
    monkeypatch.setattr(engine, "_probe_duration_seconds", lambda path: 1.5)

    async def _from_handler():
        return engine.synthesize(_sample_script(), tmp_path / "audio-async")

    result = asyncio.run(_from_handler())
    assert result.audio_path.exists()
    assert result.audio_path.read_bytes() == b"ID3fake-edge-tts"


def test_edge_tts_multi_scene_inserts_pauses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list = []
    engine = _engine(monkeypatch, edge_tts_scene_pause_ms=450)
    _patch_edge_tts(monkeypatch, calls=calls)

    def fake_probe(path: Path) -> float:
        name = Path(path).name
        if name.startswith("scene_"):
            return 1.0
        if name == "voiceover.mp3":
            return 2.45  # 1 + 0.45 + 1
        return 1.0

    monkeypatch.setattr(engine, "_probe_duration_seconds", fake_probe)

    def fake_concat(clips, dest, *, pause_ms):
        assert len(clips) == 2
        assert pause_ms == 450
        # Simulate concat output without requiring a real ffmpeg binary.
        dest.write_bytes(b"ID3concat-with-pause")

    monkeypatch.setattr(engine, "_concat_mp3_with_silence", fake_concat)

    result = engine.synthesize(_sample_script(scenes=2), tmp_path / "audio")
    assert len(calls) == 2
    assert result.audio_path.read_bytes() == b"ID3concat-with-pause"
    assert result.duration_seconds == pytest.approx(2.45)
    assert result.timing["scene_pause_seconds"] == pytest.approx(0.45)

    scenes = result.timing["scenes"]
    assert len(scenes) == 2
    assert scenes[0]["speech_duration"] == pytest.approx(1.0)
    assert scenes[0]["pause_after"] == pytest.approx(0.45)
    assert scenes[0]["duration"] == pytest.approx(1.45)
    assert scenes[1]["pause_after"] == pytest.approx(0.0)
    assert scenes[1]["duration"] == pytest.approx(1.0)
    # Visual durations include the inter-scene pause on the prior scene.
    assert result.script.scenes[0].duration == pytest.approx(1.45)
    assert result.script.scenes[1].duration == pytest.approx(1.0)


def test_pause_aware_word_timestamps_skip_silence_gaps() -> None:
    from config.settings import Settings, TTSProvider

    engine = AudioEngine(
        Settings(
            tts_provider=TTSProvider.EDGE_TTS,
            openai_api_key="unused",
            _env_file=None,
        )
    )
    script = _sample_script(scenes=2)
    words = engine._estimate_word_timestamps_with_pauses(
        script, [1.0, 1.0], pause_s=0.45
    )
    assert words
    # First scene words finish at/before 1.0; second scene starts after the gap.
    first_scene_end = max(w.end for w in words if w.start < 1.0)
    second_scene_start = min(w.start for w in words if w.start >= 1.0)
    assert first_scene_end <= 1.01
    assert second_scene_start >= 1.45


def test_edge_tts_multi_scene_falls_back_when_concat_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _engine(monkeypatch)
    _patch_edge_tts(monkeypatch)
    monkeypatch.setattr(engine, "_probe_duration_seconds", lambda path: 3.0)

    def boom(*_args, **_kwargs):
        raise RuntimeError("concat unavailable")

    monkeypatch.setattr(engine, "_concat_mp3_with_silence", boom)

    result = engine.synthesize(_sample_script(scenes=2), tmp_path / "audio")
    assert result.audio_path.exists()
    assert result.duration_seconds == 3.0
