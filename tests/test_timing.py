from __future__ import annotations

from youtube_pipeline.models import SceneData, VideoScript
from youtube_pipeline.video.timing import scene_timeline


def test_scene_timeline_is_contiguous() -> None:
    script = VideoScript(
        title="t",
        full_script="Short A longer line",
        style="documentary",
        scenes=[
            SceneData(
                scene_id=0,
                script_text="Short",
                visual_prompt="prompt a",
                keywords=["a"],
                duration=2.0,
            ),
            SceneData(
                scene_id=1,
                script_text="A longer line",
                visual_prompt="prompt b",
                keywords=["b"],
                duration=8.0,
            ),
        ],
    )
    timeline = scene_timeline(script)
    assert len(timeline) == 2
    assert timeline[0]["start"] == 0.0
    assert timeline[0]["end"] == timeline[1]["start"]
    assert timeline[-1]["end"] == 10.0
