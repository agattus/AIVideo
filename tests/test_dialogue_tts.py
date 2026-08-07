from pathlib import Path

import pytest

from youtube_pipeline.audio.tts import AudioEngine
from youtube_pipeline.models import SceneData, VideoScript


def test_dialogue_uses_character_voices_and_line_ranges_for_timing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catch dialogue falling back to one voice or scene-proportional timing."""
    from config.settings import Settings, TTSProvider

    monkeypatch.setattr(AudioEngine, "_validate_config", lambda self: None)
    engine = AudioEngine(
        Settings(
            tts_provider=TTSProvider.OPENAI,
            openai_api_key="unused",
            _env_file=None,
        )
    )
    spoken: list[tuple[str, str | None]] = []
    concat_pauses: list[int] = []

    def fake_edge(self, text, output_path, *, voice=None):
        spoken.append((text, voice))
        output_path.write_bytes(b"ID3line")

    def reject_openai(*_args, **_kwargs):
        raise AssertionError("dialogue must use Edge TTS voices")

    def fake_silence(self, dest, *, pause_ms, ffmpeg=None):
        dest.write_bytes(b"ID3silence")

    def fake_concat(self, clips, dest, *, pause_ms):
        concat_pauses.append(pause_ms)
        dest.write_bytes(b"ID3dialogue")

    def fake_probe(path: Path) -> float:
        name = Path(path).name
        if name == "line_0000.mp3":
            return 1.0
        if name == "line_0001.mp3":
            return 2.0
        if name == "line_0002.mp3":
            return 3.0
        return 6.6

    monkeypatch.setattr(AudioEngine, "_synthesize_edge_tts", fake_edge)
    monkeypatch.setattr(AudioEngine, "_synthesize_openai", reject_openai)
    monkeypatch.setattr(AudioEngine, "_make_silence_mp3", fake_silence)
    monkeypatch.setattr(AudioEngine, "_concat_mp3_with_silence", fake_concat)
    monkeypatch.setattr(engine, "_probe_duration_seconds", fake_probe)

    script = VideoScript(
        title="Gate",
        full_script="We leave. Wait. Go now.",
        style="cinematic",
        format="dialogue",
        cast=[
            {"id": "ravi", "name": "Ravi", "gender_hint": "male"},
            {"id": "maya", "name": "Maya", "gender_hint": "female"},
            {"id": "guard", "name": "Guard", "gender_hint": "male"},
        ],
        lines=[
            {"speaker_id": "ravi", "speaker_name": "Ravi", "text": "We leave."},
            {"speaker_id": "maya", "speaker_name": "Maya", "text": "Wait."},
            {"speaker_id": "guard", "speaker_name": "Guard", "text": "Go now."},
        ],
        voice_map={
            "ravi": "en-US-GuyNeural",
            "maya": "en-US-AriaNeural",
            "guard": "en-US-ChristopherNeural",
        },
        scenes=[
            SceneData(
                scene_id=0,
                script_text="We leave.\nWait.",
                visual_prompt="Two travelers at a gate",
                line_start=0,
                line_end=1,
            ),
            SceneData(
                scene_id=1,
                script_text="Go now.",
                visual_prompt="A guard opens the gate",
                line_start=2,
                line_end=2,
            ),
        ],
    )

    result = engine.synthesize(script, tmp_path / "audio")

    assert spoken == [
        ("We leave.", "en-US-GuyNeural"),
        ("Wait.", "en-US-AriaNeural"),
        ("Go now.", "en-US-ChristopherNeural"),
    ]
    assert concat_pauses == [300]
    assert result.duration_seconds == pytest.approx(6.6)
    assert result.timing["lines"] == [
        {
            "speaker_id": "ravi",
            "speaker_name": "Ravi",
            "text": "We leave.",
            "start": pytest.approx(0.0),
            "end": pytest.approx(1.3),
        },
        {
            "speaker_id": "maya",
            "speaker_name": "Maya",
            "text": "Wait.",
            "start": pytest.approx(1.3),
            "end": pytest.approx(3.6),
        },
        {
            "speaker_id": "guard",
            "speaker_name": "Guard",
            "text": "Go now.",
            "start": pytest.approx(3.6),
            "end": pytest.approx(6.6),
        },
    ]
    assert result.timing["scene_pause_seconds"] == pytest.approx(0.0)
    assert [scene.duration for scene in result.script.scenes] == pytest.approx(
        [3.6, 3.0]
    )
