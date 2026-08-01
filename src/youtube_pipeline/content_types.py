"""Content types (narration / quiz) and short/long form presets."""

from __future__ import annotations

from typing import Any

from youtube_pipeline.models import AspectRatio, ContentType, FormLength, VisualStyle

DEFAULT_QUESTION_HOLD_SECONDS = 10.0

# Presets applied when the client picks form_length (can still override duration/aspect).
FORM_PRESETS: dict[tuple[ContentType, FormLength], dict[str, Any]] = {
    (ContentType.NARRATION, FormLength.SHORT): {
        "duration": 45,
        "max_scenes": 6,
        "aspect_ratio": AspectRatio.VERTICAL,
        "style": VisualStyle.FAST_PACED_SHORTS,
        "label": "Short narrated film",
        "blurb": "Punchy story, ~45 seconds — great for Shorts and Reels.",
    },
    (ContentType.NARRATION, FormLength.LONG): {
        "duration": 180,
        "max_scenes": 16,
        "aspect_ratio": AspectRatio.LANDSCAPE,
        "style": VisualStyle.CINEMATIC,
        "label": "Long narrated film",
        "blurb": "Deeper story, ~3 minutes — classic YouTube landscape.",
    },
    (ContentType.QUIZ, FormLength.SHORT): {
        "duration": 75,
        "max_scenes": 6,  # 3 questions × (question + answer)
        "aspect_ratio": AspectRatio.VERTICAL,
        "style": VisualStyle.FAST_PACED_SHORTS,
        "questions": 3,
        "hold_seconds": DEFAULT_QUESTION_HOLD_SECONDS,
        "label": "Quiz short",
        "blurb": "3 questions — show the quiz, wait ~10s, then reveal the answer.",
    },
    (ContentType.QUIZ, FormLength.LONG): {
        "duration": 180,
        "max_scenes": 16,  # 8 questions × 2
        "aspect_ratio": AspectRatio.VERTICAL,
        "style": VisualStyle.FAST_PACED_SHORTS,
        "questions": 8,
        "hold_seconds": DEFAULT_QUESTION_HOLD_SECONDS,
        "label": "Quiz long",
        "blurb": "8 questions with think-time and answer reveals — QuizVerse style.",
    },
}


def normalize_content_type(raw: str | ContentType | None) -> ContentType:
    if isinstance(raw, ContentType):
        return raw
    text = (raw or "narration").strip().lower().replace("-", "_")
    aliases = {
        "narration": ContentType.NARRATION,
        "story": ContentType.NARRATION,
        "documentary": ContentType.NARRATION,
        "quiz": ContentType.QUIZ,
        "quizverse": ContentType.QUIZ,
        "trivia": ContentType.QUIZ,
    }
    return aliases.get(text, ContentType.NARRATION)


def normalize_form_length(raw: str | FormLength | None) -> FormLength:
    if isinstance(raw, FormLength):
        return raw
    text = (raw or "short").strip().lower()
    if text in {"long", "full", "youtube"}:
        return FormLength.LONG
    return FormLength.SHORT


def preset_for(
    content_type: ContentType | str | None,
    form_length: FormLength | str | None,
) -> dict[str, Any]:
    ct = normalize_content_type(content_type)
    fl = normalize_form_length(form_length)
    return dict(FORM_PRESETS[(ct, fl)])


def question_count_for(max_scenes: int, *, content_type: ContentType) -> int:
    if content_type != ContentType.QUIZ:
        return 0
    # Always even: question + answer pairs.
    return max(1, int(max_scenes) // 2)


def apply_form_defaults(request_data: dict[str, Any]) -> dict[str, Any]:
    """Fill duration / scenes / aspect from form_length when the client omitted them.

    Explicit client values always win. ``form_length`` alone is enough to pick a preset.
    """
    data = dict(request_data)
    ct = normalize_content_type(data.get("content_type"))
    fl = normalize_form_length(data.get("form_length"))
    preset = preset_for(ct, fl)
    data["content_type"] = ct.value
    data["form_length"] = fl.value

    if data.get("duration") in (None, "", 0):
        data["duration"] = preset["duration"]
    if data.get("max_scenes") in (None, "", 0):
        data["max_scenes"] = preset["max_scenes"]
    if not data.get("aspect_ratio"):
        ar = preset["aspect_ratio"]
        data["aspect_ratio"] = ar.value if isinstance(ar, AspectRatio) else ar
    if not data.get("style"):
        style = preset["style"]
        data["style"] = style.value if isinstance(style, VisualStyle) else style

    if ct == ContentType.QUIZ:
        # Force even scene count for Q/A pairs.
        scenes = int(data.get("max_scenes") or preset["max_scenes"])
        if scenes % 2:
            scenes += 1
        data["max_scenes"] = max(2, scenes)
        data.setdefault("hold_seconds", preset.get("hold_seconds", DEFAULT_QUESTION_HOLD_SECONDS))

    return data


def content_type_catalog() -> list[dict[str, Any]]:
    """API payload describing available content types + form lengths."""
    items: list[dict[str, Any]] = []
    for (ct, fl), preset in FORM_PRESETS.items():
        ar = preset["aspect_ratio"]
        style = preset["style"]
        items.append(
            {
                "content_type": ct.value,
                "form_length": fl.value,
                "label": preset["label"],
                "blurb": preset["blurb"],
                "duration": preset["duration"],
                "max_scenes": preset["max_scenes"],
                "aspect_ratio": ar.value if isinstance(ar, AspectRatio) else ar,
                "style": style.value if isinstance(style, VisualStyle) else style,
                "questions": preset.get("questions"),
                "hold_seconds": preset.get("hold_seconds"),
            }
        )
    return items
