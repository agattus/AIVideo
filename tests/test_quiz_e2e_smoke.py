"""End-to-end smoke: Comment mode must not leak answers into caption inputs."""

from youtube_pipeline.models import QuizMode
from youtube_pipeline.quiz.beats import assert_no_answer_leak, expand_quiz_questions
from youtube_pipeline.video.text_clips import scene_caption_timeline

QUESTIONS = [
    {
        "question": "Who is the king of the Greek gods?",
        "choices": ["Apollo", "Zeus", "Hades"],
        "answer": "Zeus",
        "explain": "Zeus rules Olympus.",
    },
    {
        "question": "Which planet is closest to the Sun?",
        "choices": ["Venus", "Mercury", "Mars"],
        "answer": "Mercury",
        "explain": "Mercury has the smallest orbit.",
    },
]


def _assert_no_answer_in_caption_timeline(scenes, questions) -> None:
    answers = [q.get("answer", "") for q in questions if q.get("answer")]
    for scene in scenes:
        if not scene.script_text.strip():
            continue
        duration = scene.hold_seconds or 3.0
        cues = scene_caption_timeline(scene.script_text, scene_duration=duration)
        caption_text = " ".join(text for text, _, _ in cues).lower()
        for answer in answers:
            if answer and answer.lower() in caption_text:
                raise AssertionError(
                    f"Answer {answer!r} leaked into caption timeline for scene {scene.scene_id}"
                )


def test_comment_mode_caption_timeline_has_no_answer_leak() -> None:
    scenes = expand_quiz_questions(QUESTIONS, mode=QuizMode.COMMENT)
    assert_no_answer_leak(scenes, QUESTIONS)
    _assert_no_answer_in_caption_timeline(scenes, QUESTIONS)
