"""Prompt builders for QuizVerse-style question → hold → answer videos."""

from __future__ import annotations

from youtube_pipeline.content_types import question_count_for
from youtube_pipeline.models import AspectRatio, ContentType, VisualStyle
from youtube_pipeline.script_engine.prompts import STYLE_GUIDANCE, build_visual_style_anchor


def build_quiz_system_prompt(
    *,
    question_count: int,
    hold_seconds: float,
    language: str = "en",
) -> str:
    from youtube_pipeline.i18n import normalize_language, script_language_name

    q = max(1, int(question_count))
    n = q * 2
    lang = normalize_language(language)
    lang_name = script_language_name(lang)
    hold = max(3, int(round(hold_seconds)))

    return f"""You are a viral quiz-show writer for short vertical videos (QuizVerse style).

FORMAT: For each quiz item you produce TWO scenes in order:
  1) phase="question" — pose a clear multiple-choice or short trivia question
  2) phase="answer" — reveal the correct answer with a short punchy explanation

LANGUAGE (NON-NEGOTIABLE):
- Write title, full_script, narration, question, and answer in {lang_name} (native script).
- Keep visual_prompt and keywords in English.

Return valid JSON only (no markdown):
{{
  "title": string,
  "full_script": string,
  "style": string,
  "scenes": [
    {{
      "scene_id": 0,
      "phase": "question",
      "question": "on-screen question text",
      "answer": null,
      "narration": "spoken line that reads the question",
      "visual_prompt": "English background art direction",
      "keywords": ["tag1", "tag2"],
      "hold_seconds": {hold},
      "duration": 0
    }},
    {{
      "scene_id": 1,
      "phase": "answer",
      "question": "same question text",
      "answer": "Correct: … — short explanation",
      "narration": "spoken reveal of the answer",
      "visual_prompt": "English background matching the question scene",
      "keywords": ["tag1", "tag2"],
      "hold_seconds": 0,
      "duration": 0
    }}
  ]
}}

HARD COUNTS:
- Exactly {q} quiz questions → exactly {n} scenes (pairs of question then answer).
- scene_id must be contiguous 0..{n - 1}.
- Odd/even pairing: scenes 0,2,4… are questions; 1,3,5… are answers.

QUIZ RULES:
- Questions must be fair, interesting, and answerable by a general audience.
- Prefer one clear correct answer (not opinion).
- On-screen `question` text should be readable in ~2–3 short lines.
- Question narration: speak the question clearly (≤25 words). Do NOT reveal the answer.
- Answer narration: "The answer is …" plus one short fact (≤30 words).
- hold_seconds on every question scene MUST be {hold} (viewer think-time before reveal).
- Answer scenes: hold_seconds 0.
- Pair question/answer visual_prompts with the SAME style lock so the background feels continuous.
- Visuals: bold, colorful, high-contrast quiz backgrounds — readable negative space for text overlays.
- Never put the answer text into the question scene.
"""


def build_quiz_user_prompt(
    *,
    idea: str,
    style: VisualStyle,
    aspect_ratio: AspectRatio,
    target_duration_seconds: int,
    max_scenes: int,
    hold_seconds: float,
    language: str = "en",
) -> str:
    from youtube_pipeline.i18n import normalize_language, script_language_name

    q = question_count_for(max_scenes, content_type=ContentType.QUIZ)
    n = q * 2
    lang = normalize_language(language)
    lang_name = script_language_name(lang)
    style_text = STYLE_GUIDANCE.get(style, STYLE_GUIDANCE[VisualStyle.FAST_PACED_SHORTS])
    style_anchor = build_visual_style_anchor(idea=idea, style=style)
    hold = max(3, int(round(hold_seconds)))

    return f"""Create a QuizVerse-style quiz video package.

TOPIC / IDEA: {idea}

NARRATION LANGUAGE: {lang_name} (code={lang})
ASPECT RATIO: {aspect_ratio.value} (compose for this frame)
TARGET RUNTIME: about {target_duration_seconds}s (including ~{hold}s think-time per question)
VISUAL STYLE: {style.value} — {style_text}

STYLE ANCHOR (prepend to EVERY visual_prompt):
{style_anchor}

COUNTS:
- Exactly {q} questions
- Exactly {n} scenes (question, answer, question, answer, …)
- Every question scene: phase=question, hold_seconds={hold}
- Every answer scene: phase=answer, hold_seconds=0

Remember: viewers see the question on screen, hear it spoken, wait ~{hold} seconds, then the answer is revealed.
"""
