"""Prompt templates for script and visual-prompt generation."""

from __future__ import annotations

import math

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

# Spoken narration pacing used to size scripts from --duration.
WORDS_PER_MINUTE = 140
SECONDS_PER_SCENE = 15


def compute_target_words(duration_seconds: int) -> int:
    """``target_words = int((duration_seconds / 60) * 140)``."""
    return max(80, int((max(1, duration_seconds) / 60) * WORDS_PER_MINUTE))


def compute_min_scenes(duration_seconds: int) -> int:
    """At least one scene per 15 seconds of audio for cinematic pacing."""
    return max(2, int(math.ceil(max(1, duration_seconds) / SECONDS_PER_SCENE)))


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
- keywords must be concrete stock-search terms (2-6 items). Prefer simple visual nouns
  that work on stock APIs (e.g. airplane, forest, detective, city skyline) — avoid
  obscure proper names as the only keywords.
- scene_id values must be contiguous starting at 0.
- Concatenating scene script_text values (with spaces) should approximately equal full_script.
- Obey the CRITICAL word-count and scene-count instructions in the user message exactly.
- Expand with rich documentary detail, context, examples, and narrative beats.
  Do NOT summarize. Do NOT write a short overview.
"""


def build_user_prompt(
    *,
    idea: str,
    style: VisualStyle,
    aspect_ratio: AspectRatio,
    target_duration_seconds: int | None,
    max_scenes: int,
) -> str:
    duration_seconds = int(target_duration_seconds or 60)
    target_words = compute_target_words(duration_seconds)
    min_scenes = compute_min_scenes(duration_seconds)
    # Honor caller max_scenes but never go below cinematic minimum for the runtime.
    scene_target = max(min_scenes, 2)
    scene_cap = max(max_scenes, min_scenes)

    style_text = STYLE_GUIDANCE[style]

    return f"""Create a complete YouTube video package for this idea:

IDEA: {idea}

STYLE: {style.value}
STYLE GUIDANCE: {style_text}
ASPECT RATIO: {aspect_ratio.value}
TARGET RUNTIME: {duration_seconds} seconds ({duration_seconds / 60:.1f} minutes)

CRITICAL: You MUST write a highly detailed, expansive documentary script that is exactly {target_words} words long. Expand heavily on the narrative. Do not summarize.

CRITICAL SCENE PACING: Produce between {scene_target} and {scene_cap} scenes (at least 1 scene per {SECONDS_PER_SCENE} seconds of audio so visuals stay cinematic). Prefer closer to {scene_target}+ scenes for longer runtimes.

Word-count check: full_script (and the concatenation of all script_text fields) must be approximately {target_words} words (accept +/- 10%).

Return a JSON object with keys: title, full_script, style, scenes.
Each scene object must include: scene_id, script_text, visual_prompt, keywords, duration.
Set style to "{style.value}" and every scene duration to 0.
Distribute narration evenly across scenes so each scene has substantial script_text.
"""
