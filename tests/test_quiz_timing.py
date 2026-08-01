"""Quiz hold padding inserts silence so questions stay on screen ~10s."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from youtube_pipeline.audio.quiz_timing import apply_quiz_holds
from youtube_pipeline.models import SceneData, VideoScript


def _make_tone(path: Path, seconds: float = 2.0) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not available")
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={seconds}",
        "-q:a",
        "9",
        "-acodec",
        "libmp3lame",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        pytest.skip(f"could not synthesize test audio: {proc.stderr[-200:]}")


def test_apply_quiz_holds_pads_short_question(tmp_path: Path) -> None:
    audio = tmp_path / "voiceover.mp3"
    # 2s question + 2s answer spoken audio, but durations marked as 2s each.
    _make_tone(audio, seconds=4.0)

    script = VideoScript(
        title="Quiz",
        full_script="Q A",
        style="fast_paced_shorts",
        scenes=[
            SceneData(
                scene_id=0,
                script_text="What is 2 plus 2?",
                visual_prompt="quiz bg",
                duration=2.0,
                phase="question",
                question="What is 2 + 2?",
                hold_seconds=10.0,
            ),
            SceneData(
                scene_id=1,
                script_text="The answer is 4.",
                visual_prompt="quiz bg",
                duration=2.0,
                phase="answer",
                answer="4",
                hold_seconds=0,
            ),
        ],
    )
    timing = {
        "scenes": [
            {"scene_id": 0, "start": 0.0, "end": 2.0},
            {"scene_id": 1, "start": 2.0, "end": 4.0},
        ],
        "words": [],
    }

    updated, out_audio, new_timing, total = apply_quiz_holds(
        script, audio, timing, default_hold=10.0
    )
    assert out_audio.exists()
    assert updated.scenes[0].duration >= 9.5
    assert updated.scenes[1].duration == pytest.approx(2.0, abs=0.3)
    assert total >= 11.5
    assert new_timing.get("quiz_holds_applied") is True
