from youtube_pipeline.models import (
    BeatType,
    PipelineRequest,
    SceneData,
    VideoFormat,
    VideoScript,
)


def test_pipeline_request_accepts_dialogue_format() -> None:
    req = PipelineRequest(
        idea="Two friends argue about coffee",
        format=VideoFormat.DIALOGUE,
    )
    assert req.format == VideoFormat.DIALOGUE
    assert req.format.value == "dialogue"


def test_scene_data_accepts_speaker_and_line_range_fields() -> None:
    scene = SceneData(
        scene_id=0,
        script_text="We leave at dawn.",
        visual_prompt="Moonlit fort gate with torchlight",
        beat_type=BeatType.NARRATION,
        speaker_id="a",
        speaker_name="Alex",
        line_start=0,
        line_end=2,
    )
    assert scene.speaker_id == "a"
    assert scene.speaker_name == "Alex"
    assert scene.line_start == 0
    assert scene.line_end == 2


def test_scene_data_speaker_fields_default_to_empty() -> None:
    scene = SceneData(
        scene_id=0,
        script_text="Hello there.",
        visual_prompt="A wide cinematic shot of a coastline",
    )
    assert scene.speaker_id is None
    assert scene.speaker_name == ""
    assert scene.line_start is None
    assert scene.line_end is None


def test_video_script_accepts_dialogue_cast_and_voice_map() -> None:
    script = VideoScript(
        title="Gate Argument",
        full_script="We leave at dawn.\nThe gate won't open.",
        style="cinematic",
        format="dialogue",
        cast=[{"id": "a", "name": "Alex", "gender_hint": "male"}],
        lines=[{"speaker_id": "a", "text": "We leave at dawn."}],
        voice_map={"a": "en-US-GuyNeural"},
        scenes=[
            SceneData(
                scene_id=0,
                script_text="We leave at dawn.",
                visual_prompt="Moonlit fort gate",
                speaker_id="a",
                speaker_name="Alex",
                line_start=0,
                line_end=0,
            ),
        ],
    )
    assert script.format == "dialogue"
    assert len(script.cast) == 1
    assert script.lines[0]["speaker_id"] == "a"
    assert script.voice_map["a"] == "en-US-GuyNeural"
