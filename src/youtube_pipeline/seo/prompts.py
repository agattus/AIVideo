"""LLM prompts for YouTube SEO packaging."""

from __future__ import annotations

from youtube_pipeline.models import PipelineRequest, VideoScript
from youtube_pipeline.seo.fallback import resolve_pack_mode


def build_seo_system_prompt(*, mode: str, language: str) -> str:
    title_limit = 70 if mode == "shorts" else 100
    chapters_rule = (
        'Return "chapters": [] for Shorts.'
        if mode == "shorts"
        else "Return 3–8 chapters with start_seconds and short labels (no spoilers)."
    )
    return (
        "You are a YouTube growth editor. Write upload packaging that ranks and gets shared.\n"
        f"Mode: {mode}. Primary language: {language}.\n"
        "Rules:\n"
        f"- primary_title: curiosity gap, concrete noun + tension, ≤{title_limit} chars, no ending spoilers, no fake clickbait.\n"
        "- alt_titles: 2–3 distinct alternatives (same rules).\n"
        "- description: hook in first 100 chars; short non-spoiler synopsis; 3 bullets; comment CTA; "
        "then one English keyword line; then hashtags.\n"
        "- tags: 8–15 specific + category terms.\n"
        "- hashtags: 3–8; include #shorts only for Shorts mode.\n"
        "- pinned_comment: one engaging question.\n"
        f"- {chapters_rule}\n"
        "- Keep body copy in the primary language; English only for the keyword line + hashtags OK.\n"
        "Return ONLY JSON with keys: primary_title, alt_titles, description, tags, hashtags, "
        "pinned_comment, chapters."
    )


def build_seo_user_prompt(
    script: VideoScript,
    request: PipelineRequest,
    *,
    timed_script: VideoScript | None = None,
) -> str:
    mode = resolve_pack_mode(request.aspect_ratio)
    language = (request.language or "en").strip() or "en"
    source = timed_script or script
    scene_lines = []
    cursor = 0.0
    for index, scene in enumerate(source.scenes[:12]):
        dur = float(scene.duration or 0.0)
        scene_lines.append(
            f"{index}|t={int(cursor)}s|{(scene.script_text or '')[:160]}"
        )
        cursor += max(0.0, dur)
    return (
        f"mode={mode}\n"
        f"language={language}\n"
        f"aspect={getattr(request.aspect_ratio, 'value', request.aspect_ratio)}\n"
        f"format={request.format.value}\n"
        f"style={script.style}\n"
        f"idea={request.idea}\n"
        f"current_title={script.title}\n"
        f"full_script={(script.full_script or '')[:1200]}\n"
        "scenes:\n"
        + "\n".join(scene_lines)
    )
