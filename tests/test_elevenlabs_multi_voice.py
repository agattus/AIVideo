"""ElevenLabs multi-voice casting + dialogue synthesis routing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from config.settings import Settings, TTSProvider
from youtube_pipeline.audio.tts import AudioEngine
from youtube_pipeline.dialogue.casting import assign_voices
from youtube_pipeline.models import VideoScript


@pytest.fixture()
def eleven_catalog(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    voices = [
        {"id": "voice_male_a", "label": "Adam", "locale": "en", "gender": "Male"},
        {"id": "voice_female_a", "label": "Rachel", "locale": "en", "gender": "Female"},
        {"id": "voice_male_b", "label": "Josh", "locale": "en", "gender": "Male"},
        {"id": "voice_female_b", "label": "Bella", "locale": "en", "gender": "Female"},
    ]

    monkeypatch.setattr(
        "youtube_pipeline.audio.elevenlabs_voices.safe_list_elevenlabs_voices",
        lambda *args, **kwargs: list(voices),
    )
    monkeypatch.setattr(
        "youtube_pipeline.audio.elevenlabs_voices.default_elevenlabs_voice_id",
        lambda: voices[0]["id"],
    )
    return voices


def test_assign_voices_elevenlabs_distinct_by_gender(eleven_catalog) -> None:
    cast = [
        {"id": "a", "name": "Ravi", "gender_hint": "male"},
        {"id": "b", "name": "Maya", "gender_hint": "female"},
        {"id": "c", "name": "Guard", "gender_hint": "male"},
    ]

    voice_map = assign_voices(cast, language="en", provider=TTSProvider.ELEVENLABS)

    assert set(voice_map) == {"a", "b", "c"}
    assert len(set(voice_map.values())) == 3
    assert voice_map["a"] == "voice_male_a"
    assert voice_map["b"] == "voice_female_a"
    assert voice_map["c"] == "voice_male_b"
    assert all(v.startswith("voice_") for v in voice_map.values())


def test_dialogue_tts_uses_elevenlabs_per_line_voice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        tts_provider=TTSProvider.ELEVENLABS,
        elevenlabs_api_key="test-key",
        elevenlabs_voice_id="default_voice",
    )
    engine = AudioEngine(settings)
    calls: list[tuple[str, str]] = []

    def fake_elevenlabs(self, text: str, output_path: Path, *, voice: str | None) -> None:
        calls.append((text, voice or ""))
        output_path.write_bytes(b"ID3fake")

    monkeypatch.setattr(AudioEngine, "_synthesize_elevenlabs", fake_elevenlabs)
    monkeypatch.setattr(
        AudioEngine,
        "_probe_duration_seconds",
        lambda self, path: 1.0,
    )
    monkeypatch.setattr(
        AudioEngine,
        "_concat_mp3_with_silence",
        lambda self, clips, output_path, pause_ms=0: Path(output_path).write_bytes(b"ID3out"),
    )
    monkeypatch.setattr(
        AudioEngine,
        "_build_dialogue_timing",
        lambda *args, **kwargs: {
            "scenes": [{"scene_id": 0, "duration": 2.3}],
            "words": [],
            "total_duration": 2.3,
        },
    )
    monkeypatch.setattr(
        AudioEngine,
        "_apply_scene_durations",
        lambda self, script, timing, total: script,
    )

    script = VideoScript(
        title="Test",
        full_script="Hello. Hi there.",
        style="cinematic",
        format="dialogue",
        cast=[
            {"id": "ravi", "name": "Ravi"},
            {"id": "maya", "name": "Maya"},
            {"id": "guard", "name": "Guard"},
        ],
        lines=[
            {"speaker_id": "ravi", "speaker_name": "Ravi", "text": "Hello."},
            {"speaker_id": "maya", "speaker_name": "Maya", "text": "Hi there."},
        ],
        voice_map={"ravi": "el_ravi", "maya": "el_maya", "guard": "el_guard"},
        scenes=[
            {
                "scene_id": 0,
                "script_text": "Hello.",
                "visual_prompt": "two characters talking",
                "duration": 1.0,
                "line_start": 0,
                "line_end": 1,
            }
        ],
    )

    out = tmp_path / "voiceover.mp3"
    result = engine._synthesize_dialogue_lines(script, out)

    assert out.exists()
    assert calls == [("Hello.", "el_ravi"), ("Hi there.", "el_maya")]
    assert result.duration_seconds > 0


def test_dialogue_tts_falls_back_to_edge_on_paid_plan_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        tts_provider=TTSProvider.ELEVENLABS,
        elevenlabs_api_key="test-key",
        elevenlabs_voice_id="default_voice",
        _env_file=None,
    )
    engine = AudioEngine(settings)

    class PaidPlanError(Exception):
        pass

    def boom(self, text: str, output_path: Path, *, voice: str | None) -> None:
        raise PaidPlanError(
            "status_code: 402, body: {'detail': {'code': 'paid_plan_required'}}"
        )

    edge_calls: list[str] = []

    def fake_edge(self, text: str, output_path: Path, *, voice: str | None) -> None:
        edge_calls.append(voice or "")
        output_path.write_bytes(b"ID3fake")

    monkeypatch.setattr(AudioEngine, "_synthesize_elevenlabs", boom)
    monkeypatch.setattr(AudioEngine, "_synthesize_edge_tts", fake_edge)
    monkeypatch.setattr(AudioEngine, "_probe_duration_seconds", lambda self, path: 1.0)
    monkeypatch.setattr(
        AudioEngine,
        "_concat_mp3_with_silence",
        lambda self, clips, output_path, pause_ms=0: Path(output_path).write_bytes(b"ID3out"),
    )
    monkeypatch.setattr(
        AudioEngine,
        "_build_dialogue_timing",
        lambda *args, **kwargs: {
            "scenes": [{"scene_id": 0, "duration": 2.3}],
            "words": [],
            "total_duration": 2.3,
        },
    )
    monkeypatch.setattr(
        AudioEngine,
        "_apply_scene_durations",
        lambda self, script, timing, total: script,
    )

    script = VideoScript(
        title="Test",
        full_script="Hello. Hi there.",
        style="cinematic",
        format="dialogue",
        cast=[
            {"id": "ravi", "name": "Ravi", "gender_hint": "male"},
            {"id": "maya", "name": "Maya", "gender_hint": "female"},
            {"id": "guard", "name": "Guard", "gender_hint": "male"},
        ],
        lines=[
            {"speaker_id": "ravi", "speaker_name": "Ravi", "text": "Hello."},
            {"speaker_id": "maya", "speaker_name": "Maya", "text": "Hi there."},
        ],
        voice_map={"ravi": "el_ravi", "maya": "el_maya", "guard": "el_guard"},
        scenes=[
            {
                "scene_id": 0,
                "script_text": "Hello.",
                "visual_prompt": "two characters talking",
                "duration": 1.0,
                "line_start": 0,
                "line_end": 1,
            }
        ],
    )

    out = tmp_path / "voiceover.mp3"
    result = engine.synthesize(script, tmp_path)

    assert out.exists()
    assert len(edge_calls) == 2
    assert all(str(v).startswith("en-") for v in edge_calls)
    assert all(str(v).startswith("en-") for v in result.script.voice_map.values())
