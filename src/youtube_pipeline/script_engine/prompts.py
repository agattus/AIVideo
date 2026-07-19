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

You MUST respond with a single JSON object that matches this schema exactly:
{
  "title": string,
  "full_script": string,
  "style": string,
  "scenes": [
    {
      "scene_id": integer >= 0,
      "script_text": string,
      "visual_prompt": string,
      "keywords": string[],
      "duration": number  // use 0; timing is filled later by TTS
    }
  ]
}

Rules:
- Output JSON only. No markdown fences. No commentary before or after the JSON.
- Every scene needs TTS-ready script_text and a highly detailed visual_prompt.
- keywords must be concrete stock-search terms (2-6 items).
- scene_id values must be contiguous starting at 0.
- Concatenating scene script_text values (with spaces) should approximately equal full_script.
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

Return a JSON object with keys: title, full_script, style, scenes.
Each scene object must include: scene_id, script_text, visual_prompt, keywords, duration.
Set style to "{style.value}" and every scene duration to 0.
"""
