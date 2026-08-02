from youtube_pipeline.models import (
    BeatType,
    PipelineRequest,
    QuizMode,
    SceneData,
    VideoFormat,
    VideoScript,
)


def test_pipeline_request_defaults_narrative():
    req = PipelineRequest(idea="Ancient myths quiz")
    assert req.format == VideoFormat.NARRATIVE
    assert req.quiz_mode is None
    assert req.question_count is None


def test_scene_data_timer_allows_empty_script_text():
    scene = SceneData(
        scene_id=0,
        script_text="",
        visual_prompt="dark quiz background",
        beat_type=BeatType.TIMER,
        hold_seconds=10.0,
        quiz_index=0,
        question="Who?",
        answer="A",
    )
    assert scene.beat_type == BeatType.TIMER
    assert scene.script_text == ""
    assert scene.hold_seconds == 10.0


def test_narrative_scene_still_requires_script_text():
    import pytest
    with pytest.raises(Exception):
        SceneData(scene_id=0, script_text="", visual_prompt="x")
