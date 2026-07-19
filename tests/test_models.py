from __future__ import annotations

import pytest
from pydantic import ValidationError

from youtube_pipeline.models import PipelineResult, SceneData, VideoScript


def test_video_script_requires_scenes() -> None:
    with pytest.raises(ValidationError):
        VideoScript(
            title="Empty",
            full_script="hi",
            style="cinematic",
            scenes=[],
        )


def test_scene_keyword_normalization() -> None:
    scene = SceneData(
        scene_id=0,
        script_text="Hello world",
        visual_prompt="A wide cinematic shot of a coastline at golden hour",
        keywords=[" Ocean ", "CLIFF", ""],
        duration=0.0,
    )
    assert scene.keywords == ["ocean", "cliff"]


def test_pipeline_result_status_normalization() -> None:
    result = PipelineResult(
        video_path="/tmp/out.mp4",
        status="Success",
        metadata={"scenes": 2},
    )
    assert result.status == "success"


def test_duplicate_scene_ids_rejected() -> None:
    with pytest.raises(ValidationError):
        VideoScript(
            title="Dupes",
            full_script="a b",
            style="documentary",
            scenes=[
                SceneData(
                    scene_id=0,
                    script_text="a",
                    visual_prompt="prompt a",
                    keywords=["a"],
                ),
                SceneData(
                    scene_id=0,
                    script_text="b",
                    visual_prompt="prompt b",
                    keywords=["b"],
                ),
            ],
        )
