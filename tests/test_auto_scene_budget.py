from youtube_pipeline.models import AspectRatio, QuizMode, VideoFormat
from youtube_pipeline.script_engine.prompts import resolve_auto_scene_budget


def test_video_format_accepts_dialogue() -> None:
    assert VideoFormat("dialogue") is VideoFormat.DIALOGUE


def test_dialogue_vertical_budget() -> None:
    duration, scenes = resolve_auto_scene_budget(
        format=VideoFormat.DIALOGUE,
        aspect_ratio=AspectRatio.VERTICAL,
    )

    assert (duration, scenes) == (75, 6)


def test_quizverse_comment_budget_follows_question_count() -> None:
    duration, scenes = resolve_auto_scene_budget(
        format=VideoFormat.QUIZVERSE,
        aspect_ratio=AspectRatio.VERTICAL,
        quiz_mode=QuizMode.COMMENT,
        question_count=3,
    )

    assert (duration, scenes) == (30, 8)


def test_quizverse_reveal_budget_follows_question_count() -> None:
    duration, scenes = resolve_auto_scene_budget(
        format=VideoFormat.QUIZVERSE,
        aspect_ratio=AspectRatio.LANDSCAPE,
        quiz_mode=QuizMode.REVEAL,
        question_count=5,
    )

    assert (duration, scenes) == (110, 17)


def test_narrative_vertical_budget() -> None:
    assert resolve_auto_scene_budget(
        format=VideoFormat.NARRATIVE,
        aspect_ratio=AspectRatio.VERTICAL,
    ) == (45, 6)


def test_narrative_landscape_and_square_budget() -> None:
    for aspect_ratio in (AspectRatio.LANDSCAPE, AspectRatio.SQUARE):
        assert resolve_auto_scene_budget(
            format=VideoFormat.NARRATIVE,
            aspect_ratio=aspect_ratio,
        ) == (90, 10)
