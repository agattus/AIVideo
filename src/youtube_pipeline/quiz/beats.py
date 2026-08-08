"""Expand quiz question dicts into timed SceneData beats."""

from __future__ import annotations

import re

from youtube_pipeline.models import BeatType, QuizMode, SceneData
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)

REVEAL_QUESTION_HOLD = 5.0
REVEAL_TIMER_HOLD = 10.0
REVEAL_REVEAL_HOLD = 5.0

COMMENT_HOOK_HOLD = 2.0
COMMENT_QUESTION_HOLD = 4.0
COMMENT_TIMER_HOLD = 4.0
COMMENT_CTA_HOLD = 3.0

_HOOK_SCRIPT = "Think you know the answers? Let's find out!"
_CTA_SCRIPT_EN = "Drop your answers in the comments!"


def _visual_prompt(question: str) -> str:
    # Backgrounds only — quiz text/emoji are burned as overlays. Asking the
    # image model to paint the question causes wrong/extra glyphs and fights VO.
    topic = (question or "trivia").strip()
    return (
        f"Cinematic atmosphere background for a trivia quiz about: {topic}. "
        "Photoreal scene, sharp subject, no text, no letters, no numbers, "
        "no logos, no watermarks, no UI, no emoji."
    )


def _question_script(question: str, choices: list[str], *, include_choices: bool) -> str:
    if include_choices and choices:
        choices_text = ", ".join(choices)
        return f"{question} Choices: {choices_text}."
    return question


def _cta_script(language: str) -> str:
    if language != "en":
        logger.warning(
            "Using English CTA fallback for Quizverse comment mode | language=%s",
            language,
        )
    return _CTA_SCRIPT_EN


def expand_quiz_questions(
    questions: list[dict],
    *,
    mode: QuizMode,
    language: str = "en",
    target_scene_count: int | None = None,
) -> list[SceneData]:
    scenes: list[SceneData] = []
    scene_id = 0

    if mode == QuizMode.COMMENT:
        scenes.append(
            SceneData(
                scene_id=scene_id,
                script_text=_HOOK_SCRIPT,
                visual_prompt="Quiz hook: engaging trivia intro",
                beat_type=BeatType.HOOK,
                hold_seconds=COMMENT_HOOK_HOLD,
            )
        )
        scene_id += 1

    for quiz_index, q in enumerate(questions):
        question = q["question"]
        choices = list(q.get("choices") or [])
        answer = q.get("answer", "")
        explain = q.get("explain", "")

        if mode == QuizMode.REVEAL:
            question_hold = REVEAL_QUESTION_HOLD
            timer_hold = REVEAL_TIMER_HOLD
        else:
            question_hold = COMMENT_QUESTION_HOLD
            timer_hold = COMMENT_TIMER_HOLD

        include_choices = mode == QuizMode.REVEAL
        scenes.append(
            SceneData(
                scene_id=scene_id,
                script_text=_question_script(question, choices, include_choices=include_choices),
                visual_prompt=_visual_prompt(question),
                beat_type=BeatType.QUESTION,
                quiz_index=quiz_index,
                question=question,
                choices=choices,
                answer=answer,
                explain=explain,
                hold_seconds=question_hold,
            )
        )
        scene_id += 1

        scenes.append(
            SceneData(
                scene_id=scene_id,
                script_text="",
                visual_prompt=_visual_prompt(question),
                beat_type=BeatType.TIMER,
                quiz_index=quiz_index,
                question=question,
                choices=choices,
                answer=answer,
                explain=explain,
                hold_seconds=timer_hold,
            )
        )
        scene_id += 1

        if mode == QuizMode.REVEAL:
            reveal_text = f"{answer}. {explain}" if explain else answer
            scenes.append(
                SceneData(
                    scene_id=scene_id,
                    script_text=reveal_text,
                    visual_prompt=_visual_prompt(question),
                    beat_type=BeatType.REVEAL,
                    quiz_index=quiz_index,
                    question=question,
                    choices=choices,
                    answer=answer,
                    explain=explain,
                    hold_seconds=REVEAL_REVEAL_HOLD,
                )
            )
            scene_id += 1

    if mode == QuizMode.COMMENT:
        scenes.append(
            SceneData(
                scene_id=scene_id,
                script_text=_cta_script(language),
                visual_prompt="Quiz call-to-action: comment your answers",
                beat_type=BeatType.CTA,
                hold_seconds=COMMENT_CTA_HOLD,
            )
        )

    target = min(240, max(len(scenes), int(target_scene_count or len(scenes))))
    extra_count = target - len(scenes)
    if extra_count:
        insertion_index = len(scenes) - 1 if mode == QuizMode.COMMENT else len(scenes)
        broll = [
            SceneData(
                scene_id=0,
                script_text="Stay sharp. The next clue could change everything.",
                visual_prompt=f"Quiz atmosphere B-roll transition {index + 1}",
                beat_type=BeatType.NARRATION,
                hold_seconds=3.0,
            )
            for index in range(extra_count)
        ]
        scenes[insertion_index:insertion_index] = broll

    return [
        scene.model_copy(update={"scene_id": scene_id})
        for scene_id, scene in enumerate(scenes)
    ]


def assert_no_answer_leak(scenes: list[SceneData], questions: list[dict]) -> None:
    answers = [q.get("answer", "") for q in questions if q.get("answer")]
    for scene in scenes:
        spoken = scene.script_text.casefold()
        for answer in answers:
            normalized_answer = answer.casefold().strip()
            if normalized_answer and re.search(
                rf"(?<!\w){re.escape(normalized_answer)}(?!\w)",
                spoken,
            ):
                raise ValueError(
                    f"Answer {answer!r} leaked into script_text of scene {scene.scene_id}"
                )
