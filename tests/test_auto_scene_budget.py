from youtube_pipeline.models import AspectRatio, QuizMode, VideoFormat
from youtube_pipeline.script_engine.prompts import resolve_auto_scene_budget


def test_video_format_accepts_dialogue() -> None:
    assert VideoFormat("dialogue") is VideoFormat.DIALOGUE


def test_dialogue_vertical_budget() -> None:
    duration, scenes = resolve_auto_scene_budget(
        format=VideoFormat.DIALOGUE,
        aspect_ratio=AspectRatio.VERTICAL,
    )

    assert (duration, scenes) == (75, 12)


def test_dialogue_budget_uses_creator_duration_and_line_band() -> None:
    duration, scenes = resolve_auto_scene_budget(
        format=VideoFormat.DIALOGUE,
        aspect_ratio=AspectRatio.VERTICAL,
        duration_seconds=90,
    )

    assert duration == 90
    assert scenes == 15


def test_quizverse_comment_budget_follows_question_count() -> None:
    duration, scenes = resolve_auto_scene_budget(
        format=VideoFormat.QUIZVERSE,
        aspect_ratio=AspectRatio.VERTICAL,
        quiz_mode=QuizMode.COMMENT,
        question_count=3,
    )

    assert (duration, scenes) == (30, 8)


def test_quizverse_comment_budget_honors_duration_with_broll_headroom() -> None:
    assert resolve_auto_scene_budget(
        format=VideoFormat.QUIZVERSE,
        aspect_ratio=AspectRatio.VERTICAL,
        quiz_mode=QuizMode.COMMENT,
        question_count=3,
        duration_seconds=90,
    ) == (90, 11)


def test_quizverse_reveal_budget_follows_question_count() -> None:
    duration, scenes = resolve_auto_scene_budget(
        format=VideoFormat.QUIZVERSE,
        aspect_ratio=AspectRatio.LANDSCAPE,
        quiz_mode=QuizMode.REVEAL,
        question_count=5,
    )

    assert (duration, scenes) == (110, 17)


def test_quizverse_reveal_budget_honors_longer_creator_duration() -> None:
    assert resolve_auto_scene_budget(
        format=VideoFormat.QUIZVERSE,
        aspect_ratio=AspectRatio.LANDSCAPE,
        quiz_mode=QuizMode.REVEAL,
        question_count=5,
        duration_seconds=150,
    ) == (150, 19)


def test_narrative_vertical_budget() -> None:
    assert resolve_auto_scene_budget(
        format=VideoFormat.NARRATIVE,
        aspect_ratio=AspectRatio.VERTICAL,
    ) == (45, 6)


def test_narrative_max_scenes_scales_with_duration() -> None:
    _, short = resolve_auto_scene_budget(
        format=VideoFormat.NARRATIVE,
        aspect_ratio=AspectRatio.VERTICAL,
        duration_seconds=45,
    )
    _, long = resolve_auto_scene_budget(
        format=VideoFormat.NARRATIVE,
        aspect_ratio=AspectRatio.VERTICAL,
        duration_seconds=120,
    )

    assert long > short
    assert short >= 6


def test_narrative_landscape_and_square_budget() -> None:
    for aspect_ratio in (AspectRatio.LANDSCAPE, AspectRatio.SQUARE):
        assert resolve_auto_scene_budget(
            format=VideoFormat.NARRATIVE,
            aspect_ratio=aspect_ratio,
        ) == (90, 10)


def test_creator_duration_is_clamped_to_supported_range() -> None:
    assert resolve_auto_scene_budget(
        format=VideoFormat.NARRATIVE,
        aspect_ratio=AspectRatio.VERTICAL,
        duration_seconds=1,
    )[0] == 15
    assert resolve_auto_scene_budget(
        format=VideoFormat.NARRATIVE,
        aspect_ratio=AspectRatio.VERTICAL,
        duration_seconds=9999,
    )[0] == 3600
