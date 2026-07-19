from __future__ import annotations

from youtube_pipeline.audio.tts import AudioEngine, WORDS_PER_MINUTE
from youtube_pipeline.models import SceneData, VideoScript


def test_populate_scene_durations_scales_to_total(monkeypatch) -> None:
    # Bypass API-key validation for offline timing tests.
    monkeypatch.setattr(AudioEngine, "_validate_config", lambda self: None)
    engine = AudioEngine.__new__(AudioEngine)

    script = VideoScript(
        title="Timing",
        full_script="One two three four five six",
        style="cinematic",
        scenes=[
            SceneData(
                scene_id=0,
                script_text="One two three",
                visual_prompt="prompt a",
                keywords=["a"],
            ),
            SceneData(
                scene_id=1,
                script_text="four five six",
                visual_prompt="prompt b",
                keywords=["b"],
            ),
        ],
    )

    timed = engine.populate_scene_durations(script, total_duration=6.0)
    assert abs(timed.total_duration - 6.0) < 0.05
    assert all(scene.duration > 0 for scene in timed.scenes)


def test_estimate_duration_wpm() -> None:
    # 150 words => ~60 seconds at 150 WPM
    text = " ".join(["word"] * 150)
    seconds = AudioEngine.estimate_duration_wpm(text, wpm=WORDS_PER_MINUTE)
    assert abs(seconds - 60.0) < 0.01
