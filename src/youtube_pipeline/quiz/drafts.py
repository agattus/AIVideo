"""Community post drafts for Quizverse comment-mode quizzes."""

from __future__ import annotations


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
