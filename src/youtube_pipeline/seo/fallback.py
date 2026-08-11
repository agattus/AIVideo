"""Story-specific SEO pack when the LLM is unavailable."""

from __future__ import annotations

import re
from typing import Any

from youtube_pipeline.models import AspectRatio, PipelineRequest, VideoScript
from youtube_pipeline.seo.models import YoutubeChapter, YoutubePack

_WORD_RE = re.compile(r"[A-Za-z0-9\u0C00-\u0C7F']+")


def resolve_pack_mode(aspect_ratio: AspectRatio | str | None) -> str:
    value = getattr(aspect_ratio, "value", aspect_ratio) or "16:9"
    return "shorts" if str(value).strip() == "9:16" else "longform"


def clamp_title(title: str, *, mode: str) -> str:
    limit = 70 if mode == "shorts" else 100
    text = " ".join((title or "").split()).strip() or "Untitled film"
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _scene_blurbs(script: VideoScript, *, limit: int = 3) -> list[str]:
    blurbs: list[str] = []
    for scene in script.scenes[:limit]:
        text = " ".join((scene.script_text or "").split()).strip()
        if text:
            blurbs.append(text[:140])
    return blurbs


def _keyword_tags(script: VideoScript, request: PipelineRequest, *, limit: int = 12) -> list[str]:
    bag: list[str] = []
    for raw in (script.title, request.idea, script.style):
        bag.extend(_WORD_RE.findall(str(raw or "")))
    for scene in script.scenes[:8]:
        for kw in scene.keywords or []:
            bag.extend(_WORD_RE.findall(str(kw)))
        bag.extend(_WORD_RE.findall(scene.script_text or "")[:4])
    seen: set[str] = set()
    tags: list[str] = []
    for token in bag:
        key = token.casefold()
        if len(token) < 3 or key in seen:
            continue
        seen.add(key)
        tags.append(token)
        if len(tags) >= limit:
            break
    return tags


def _chapters_from_script(script: VideoScript, *, mode: str) -> list[YoutubeChapter]:
    if mode == "shorts":
        return []
    chapters: list[YoutubeChapter] = []
    cursor = 0.0
    for index, scene in enumerate(script.scenes):
        label = " ".join((scene.script_text or "").split())[:48] or f"Beat {index + 1}"
        chapters.append(YoutubeChapter(start_seconds=int(cursor), label=label))
        cursor += max(0.0, float(scene.duration or 0.0))
        if len(chapters) >= 8:
            break
    return chapters


def build_fallback_pack(
    script: VideoScript,
    request: PipelineRequest,
    *,
    timed_script: VideoScript | None = None,
) -> YoutubePack:
    mode = resolve_pack_mode(request.aspect_ratio)
    language = (request.language or "en").strip() or "en"
    base_title = clamp_title(script.title or request.idea or "Untitled film", mode=mode)
    idea = " ".join((request.idea or "").split()).strip()
    blurbs = _scene_blurbs(timed_script or script)
    tags = _keyword_tags(script, request)
    english_line = f"Keywords: {', '.join(tags[:8])}" if tags else f"Keywords: {idea or base_title}"

    if mode == "shorts":
        hashtags = ["#shorts", "#story", "#viral", "#cinematic"]
        if language.lower().startswith("te"):
            hashtags.append("#telugu")
    else:
        hashtags = ["#story", "#documentary", "#cinematic", "#youtube"]
        if language.lower().startswith("te"):
            hashtags.append("#telugustories")

    lines = [
        f"{base_title} — watch till the end.",
        "",
        idea or f"A {script.style or 'cinematic'} story from S-Studio.",
        "",
        "In this video:",
    ]
    for blurb in blurbs or ["The setup", "The turn", "The lasting image"]:
        lines.append(f"• {blurb}")
    lines.extend(
        [
            "",
            "If you stayed for the ending, comment: what would YOU do next?",
            "",
            english_line,
            "",
            " ".join(hashtags),
        ]
    )

    alt = [
        clamp_title(f"{base_title} | Full story", mode=mode),
        clamp_title(f"Why {base_title} hits different", mode=mode),
        clamp_title(idea or base_title, mode=mode),
    ]
    # Ensure alts differ from primary when possible.
    alt_titles = [t for t in alt if t.casefold() != base_title.casefold()][:3]

    timed = timed_script or script
    return YoutubePack(
        mode=mode,  # type: ignore[arg-type]
        language=language,
        primary_title=base_title,
        alt_titles=alt_titles,
        description="\n".join(lines),
        tags=tags,
        hashtags=hashtags,
        pinned_comment=f"What would you do next after “{base_title}”? Reply below 👇",
        chapters=_chapters_from_script(timed, mode=mode),
        source="fallback",
    )
