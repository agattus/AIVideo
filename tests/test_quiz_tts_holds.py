from pathlib import Path

import pytest

from youtube_pipeline.audio.tts import AudioEngine
from youtube_pipeline.models import BeatType, SceneData, VideoScript


def test_quizverse_timer_is_silent_and_spoken_beats_honor_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from config.settings import Settings, TTSProvider

    settings = Settings(
        tts_provider=TTSProvider.EDGE_TTS,
        _env_file=None,
        openai_api_key="x",
    )
    monkeypatch.setattr(AudioEngine, "_validate_config", lambda self: None)
    engine = AudioEngine(settings)

    spoken: list[str] = []
    silence_ms: list[int] = []
    concat_pauses: list[int] = []

    def fake_edge(self, text, output_path, *, voice=None):
        spoken.append(text)
        output_path.write_bytes(b"ID3speech")

    def fake_silence(self, dest, *, pause_ms, ffmpeg=None):
        silence_ms.append(pause_ms)
        dest.write_bytes(b"ID3silence")

    def fake_concat(self, clips, dest, *, pause_ms):
        concat_pauses.append(pause_ms)
        dest.write_bytes(b"ID3joined")

    monkeypatch.setattr(AudioEngine, "_synthesize_edge_tts", fake_edge)
    monkeypatch.setattr(AudioEngine, "_make_silence_mp3", fake_silence)
    monkeypatch.setattr(AudioEngine, "_concat_mp3_with_silence", fake_concat)
    monkeypatch.setattr(
        engine,
        "_probe_duration_seconds",
        lambda path: 4.0 if Path(path).name.startswith("scene_") else 13.0,
    )

    script = VideoScript(
        title="Q",
        full_script="Who? Comment below",
        style="cinematic",
        format="quizverse",
        scenes=[
            SceneData(
                scene_id=0,
                script_text="Who?",
                visual_prompt="q",
                beat_type=BeatType.QUESTION,
                hold_seconds=5,
                question="Who?",
            ),
            SceneData(
                scene_id=1,
                script_text="",
                visual_prompt="t",
                beat_type=BeatType.TIMER,
                hold_seconds=4,
                question="Who?",
                answer="A",
            ),
            SceneData(
                scene_id=2,
                script_text="Comment below",
                visual_prompt="c",
                beat_type=BeatType.CTA,
                hold_seconds=3,
            ),
        ],
    )

    result = engine.synthesize(script, tmp_path / "audio", use_per_scene_text=True)

    assert spoken == ["Who?", "Comment below"]
    assert silence_ms == [1000, 4000]
    assert concat_pauses and all(pause == 0 for pause in concat_pauses)
    assert result.duration_seconds == pytest.approx(13.0)
    assert [scene.duration for scene in result.script.scenes] == pytest.approx(
        [5.0, 4.0, 4.0]
    )
    timer_timing = result.timing["scenes"][1]
    assert timer_timing["speech_duration"] == pytest.approx(4.0)
    assert timer_timing["pause_after"] == pytest.approx(0.0)
