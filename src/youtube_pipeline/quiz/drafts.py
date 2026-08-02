"""Community post drafts for Quizverse comment-mode quizzes."""

from __future__ import annotations

from youtube_pipeline.models import VideoScript


def extract_quiz_questions(script: VideoScript) -> list[dict]:
    """Return persisted LLM questions, or reconstruct them from expanded beats."""
    if script.questions_raw:
        return [dict(question) for question in script.questions_raw]

    by_index: dict[int, dict] = {}
    for scene in script.scenes:
        if scene.quiz_index is None or not scene.question:
            continue
        by_index.setdefault(
            scene.quiz_index,
            {
                "question": scene.question,
                "choices": list(scene.choices),
                "answer": scene.answer,
                "explain": scene.explain,
            },
        )
    return [by_index[index] for index in sorted(by_index)]


def build_community_post_draft(title: str, questions: list[dict]) -> str:
    lines = [title, ""]
    for index, q in enumerate(questions, start=1):
        question = q["question"]
        choices = q.get("choices") or []
        answer = q.get("answer", "")
        explain = q.get("explain", "")

        lines.append(f"{index}. {question}")
        for choice in choices:
            lines.append(f"   - {choice}")
        lines.append(f"   Answer: {answer}")
        if explain:
            lines.append(f"   {explain}")
        lines.append("")

    lines.append("Reply in the comments — answers revealed tomorrow!")
    return "\n".join(lines)
