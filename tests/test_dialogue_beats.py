import pytest

from youtube_pipeline.dialogue.beats import expand_dialogue_script


CAST = [
    {"id": "a", "name": "Ravi", "gender_hint": "male"},
    {"id": "b", "name": "Maya", "gender_hint": "female"},
    {"id": "c", "name": "Old Guard", "gender_hint": "male"},
]

LINES = [
    {"speaker_id": "a", "text": "We leave at dawn."},
    {"speaker_id": "b", "text": "The gate won't open."},
    {"speaker_id": "c", "text": "Then we climb."},
]


def test_expand_dialogue_one_scene_per_line() -> None:
    beats = [
        {"visual_prompt": "Moonlit fort gate", "line_start": 0, "line_end": 1},
        {"visual_prompt": "Climbing the wall", "line_start": 2, "line_end": 2},
    ]
    scenes, normalized = expand_dialogue_script(
        cast=CAST, lines=LINES, visual_beats=beats
    )
    assert len(scenes) == len(LINES) == 3
    assert [(s.line_start, s.line_end) for s in scenes] == [(0, 0), (1, 1), (2, 2)]
    assert scenes[0].speaker_name == "Ravi"
    assert scenes[1].speaker_name == "Maya"
    assert "Moonlit" in scenes[0].visual_prompt
    assert scenes[0].visual_prompt != scenes[1].visual_prompt or "Maya" in scenes[1].visual_prompt
    assert scenes[0].script_text == "We leave at dawn."


def test_expand_dialogue_builds_visual_scenes_and_normalizes_speakers() -> None:
    beats = [
        {"visual_prompt": "Moonlit fort gate", "line_start": 0, "line_end": 1},
        {"visual_prompt": "The guard points toward the wall", "line_start": 2, "line_end": 2},
    ]

    scenes, normalized_lines = expand_dialogue_script(
        cast=CAST,
        lines=LINES,
        visual_beats=beats,
    )

    assert [scene.scene_id for scene in scenes] == [0, 1, 2]
    assert (
        scenes[0].visual_prompt
        == "Moonlit fort gate. Focus on Ravi: We leave at dawn."
    )
    assert scenes[0].line_start == 0
    assert scenes[0].line_end == 0
    assert scenes[0].script_text == "We leave at dawn."
    assert normalized_lines == [
        {"speaker_id": "a", "speaker_name": "Ravi", "text": "We leave at dawn."},
        {"speaker_id": "b", "speaker_name": "Maya", "text": "The gate won't open."},
        {"speaker_id": "c", "speaker_name": "Old Guard", "text": "Then we climb."},
    ]


@pytest.mark.parametrize(
    ("cast", "lines", "beats", "message"),
    [
        (CAST[:2], LINES[:2], [{"visual_prompt": "Gate", "line_start": 0, "line_end": 1}], "3 or 4"),
        (
            CAST,
            [{"speaker_id": "missing", "text": "Who goes there?"}],
            [{"visual_prompt": "Gate", "line_start": 0, "line_end": 0}],
            "speaker_id",
        ),
        (
            CAST,
            LINES,
            [{"visual_prompt": "Gate", "line_start": 0, "line_end": 1}],
            "cover",
        ),
        (
            CAST,
            LINES,
            [
                {"visual_prompt": "Gate", "line_start": 0, "line_end": 1},
                {"visual_prompt": "Wall", "line_start": 1, "line_end": 2},
            ],
            "overlap",
        ),
    ],
)
def test_expand_dialogue_rejects_invalid_cast_lines_and_beat_coverage(
    cast: list[dict],
    lines: list[dict],
    beats: list[dict],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        expand_dialogue_script(cast=cast, lines=lines, visual_beats=beats)
