from youtube_pipeline.models import BeatType, QuizMode
from youtube_pipeline.quiz.beats import assert_no_answer_leak, expand_quiz_questions
from youtube_pipeline.quiz.drafts import build_community_post_draft

QUESTIONS = [
    {
        "question": "Who is the king of the Greek gods?",
        "choices": ["Apollo", "Zeus", "Hades"],
        "answer": "Zeus",
        "explain": "Zeus rules Olympus.",
    }
]


def test_reveal_mode_timings():
    scenes = expand_quiz_questions(QUESTIONS, mode=QuizMode.REVEAL)
    types = [s.beat_type for s in scenes]
    assert BeatType.QUESTION in types
    assert BeatType.TIMER in types
    assert BeatType.REVEAL in types
    assert BeatType.CTA not in types
    q = next(s for s in scenes if s.beat_type == BeatType.QUESTION)
    t = next(s for s in scenes if s.beat_type == BeatType.TIMER)
    r = next(s for s in scenes if s.beat_type == BeatType.REVEAL)
    assert q.hold_seconds == 5.0
    assert t.hold_seconds == 10.0
    assert r.hold_seconds == 5.0
    assert t.script_text == ""
    assert "Zeus" in r.script_text


def test_comment_mode_hides_answer_from_speech_and_has_cta():
    scenes = expand_quiz_questions(QUESTIONS, mode=QuizMode.COMMENT)
    assert any(s.beat_type == BeatType.CTA for s in scenes)
    assert not any(s.beat_type == BeatType.REVEAL for s in scenes)
    spoken = " ".join(s.script_text for s in scenes)
    assert "Zeus" not in spoken
    assert_no_answer_leak(scenes, QUESTIONS)


def test_community_draft_includes_answers_for_creator():
    draft = build_community_post_draft("Greek Quiz", QUESTIONS)
    assert "Zeus" in draft
    assert "comments" in draft.lower()
