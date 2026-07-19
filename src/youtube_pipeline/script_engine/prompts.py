"""Prompt templates for script and visual-prompt generation."""

from __future__ import annotations

from youtube_pipeline.models import AspectRatio, VisualStyle

STYLE_GUIDANCE: dict[VisualStyle, str] = {
    VisualStyle.CINEMATIC: (
        "Cinematic storytelling: dramatic lighting, shallow depth of field, "
        "widescreen composition, rich color grading, slow purposeful pacing."
    ),
    VisualStyle.DOCUMENTARY: (
        "Documentary realism: natural light, observational framing, "
        "authentic locations, understated color, informative pacing."
    ),
    VisualStyle.CORPORATE: (
        "Corporate polish: clean modern offices, confident talent, "
        "bright balanced lighting, brand-safe color, professional pacing."
    ),
    VisualStyle.FAST_PACED_SHORTS: (
        "Short-form energy: punchy cuts, bold simple compositions, "
        "high contrast, vertical-friendly framing, rapid scene changes."
    ),
    VisualStyle.ANIMATED: (
        "Stylized illustration/animation look: clear shapes, expressive color, "
        "readable silhouettes, consistent art direction across scenes."
    ),
    VisualStyle.MINIMAL: (
        "Minimal aesthetic: negative space, soft neutrals, few subjects, "
        "calm motion, elegant typography-friendly backgrounds."
    ),
}


SYSTEM_PROMPT = """You are an expert YouTube showrunner, voiceover writer, and visual prompt engineer.
You produce structured JSON only — no markdown fences, no commentary.
Every scene must include narration suitable for TTS and a highly detailed visual prompt
tailored to the requested style.
"""


def build_user_prompt(
    *,
    idea: str,
    style: VisualStyle,
    aspect_ratio: AspectRatio,
    target_duration_seconds: int | None,
    max_scenes: int,
) -> str:
    duration_clause = (
        f"Target total runtime is about {target_duration_seconds} seconds."
        if target_duration_seconds
        else "Choose a natural short-form or mid-form length."
    )
    style_text = STYLE_GUIDANCE[style]

    return f"""Create a complete YouTube video package for this idea:

IDEA: {idea}

STYLE: {style.value}
STYLE GUIDANCE: {style_text}
ASPECT RATIO: {aspect_ratio.value}
{duration_clause}
Use between 2 and {max_scenes} scenes.

Return JSON with this exact schema:
{{
  "title": "string",
  "full_script": "complete voiceover as a single string",
  "scenes": [
    {{
      "index": 0,
      "narration": "spoken line(s) for this scene",
      "visual_prompt": "detailed image/video generation prompt matching STYLE",
      "keywords": ["stock-search", "keywords"],
      "duration_hint_seconds": 5.0
    }}
  ],
  "metadata": {{
    "hook": "opening hook sentence",
    "cta": "optional call to action"
  }}
}}

Rules:
- Narration must be natural spoken English suitable for TTS.
- visual_prompt must be self-contained, highly specific, and style-consistent.
- keywords must be 2-6 concrete search terms for stock media APIs.
- Scene indices must be contiguous starting at 0.
- Concatenating scene narrations (with spaces) should approximately equal full_script.
"""
