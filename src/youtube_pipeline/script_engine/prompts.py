"""Prompt templates for script and visual-prompt generation."""

from __future__ import annotations

import math
import re

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

_STYLE_LOCK_MARKER = "continuous character design"


def compute_target_words(duration_seconds: int) -> int:
    """``target_words = int((duration_seconds / 60) * 140)``."""
    return max(80, int((max(1, duration_seconds) / 60) * WORDS_PER_MINUTE))


def compute_min_scenes(duration_seconds: int) -> int:
    """At least one scene per 15 seconds of audio for cinematic pacing."""
    return max(2, int(math.ceil(max(1, duration_seconds) / SECONDS_PER_SCENE)))


def build_visual_style_anchor(*, idea: str, style: VisualStyle | str) -> str:
    """Build the global style lock prepended to every ``visual_prompt``.

    Example shape:
    ``(Epic cinematic ancient Indian mythology, hyper-detailed, continuous
    character design)``
    """
    style_value = (style.value if isinstance(style, VisualStyle) else str(style)).strip().lower()
    style_label = style_value.replace("_", " ")
    subject = " ".join((idea or "the story").strip().split())
    # Keep the anchor compact so Pollinations URL length stays manageable.
    if len(subject) > 140:
        subject = subject[:137].rstrip() + "..."
    # Avoid "cinematic cinematic" when style is already cinematic.
    if style_value == "cinematic":
        head = f"(Epic cinematic portrayal of {subject}"
    else:
        head = f"(Epic cinematic {style_label} portrayal of {subject}"
    return f"{head}, hyper-detailed, {_STYLE_LOCK_MARKER})"


def ensure_visual_prompt_has_anchor(visual_prompt: str, anchor: str) -> str:
    """Prepend ``anchor`` when the LLM omitted the global style lock."""
    text = (visual_prompt or "").strip()
    if not text:
        return f"{anchor}: atmospheric establishing shot, ancient materials, period-accurate detail"
    if _STYLE_LOCK_MARKER in text.lower():
        return text
    # Also accept prompts that already start with the same parenthetical lock.
    compact_anchor = re.sub(r"\s+", " ", anchor).strip().lower()
    if text.lower().startswith(compact_anchor[:48]):
        return text
    return f"{anchor}: {text}"


SYSTEM_PROMPT = """You are an expert YouTube showrunner, voiceover writer, and visual prompt engineer
for generative AI image models (NOT stock footage search).

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
- scene_id values must be contiguous starting at 0.
- Concatenating scene script_text values (with spaces) should approximately equal full_script.
- Obey the CRITICAL word-count and scene-count instructions in the user message exactly.
- Expand with rich documentary detail, context, examples, and narrative beats.
  Do NOT summarize. Do NOT write a short overview.

CRITICAL — VISUAL CONSISTENCY & CHARACTER LOCK (applies to EVERY visual_prompt):
- First invent ONE global STYLE ANCHOR for the whole video from the idea's era,
  culture, mythology, and core subjects (characters, creatures, sacred objects).
- EVERY visual_prompt MUST begin with that exact same STYLE ANCHOR, then a colon,
  then the scene-specific shot. Format example:
  "(Epic cinematic ancient Indian mythology, hyper-detailed, continuous character design: [scene specifics])."
- Keep character faces, costumes, body types, divine attributes, and color palette
  identical across all scenes. Treat this as a single continuous character design bible.
- Do NOT use modern terms or modern objects (no cruise ships, cars, skyscrapers,
  smartphones, jeans, neon lights, plastic, airports, etc.).
- Describe the exact clothing, era, architecture, and ancient materials
  (e.g., ancient wooden ark, golden divine fish, saffron robes, carved stone temples,
  bronze weapons, oil lamps, river reed boats).
- Prefer period-accurate materials: wood, stone, bronze, gold, clay, silk, hemp, firelight.
- keywords must be era/character continuity tags (2-6 items), NOT modern stock-search nouns.
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
    style_anchor = build_visual_style_anchor(idea=idea, style=style)

    return f"""Create a complete YouTube video package for this idea:

IDEA: {idea}

STYLE: {style.value}
STYLE GUIDANCE: {style_text}
ASPECT RATIO: {aspect_ratio.value}
TARGET RUNTIME: {duration_seconds} seconds ({duration_seconds / 60:.1f} minutes)

GLOBAL VISUAL STYLE ANCHOR (use this EXACT prefix on EVERY visual_prompt):
{style_anchor}

CRITICAL VISUAL PROMPT RULES:
- Every visual_prompt MUST start with the GLOBAL VISUAL STYLE ANCHOR above, then ": ", then scene specifics.
- Example shape: "{style_anchor}: Manu stands on an ancient wooden ark as a golden divine fish guides him through floodwaters, saffron robes, oil-lamp firelight, carved riverbank temples."
- Do not use modern terms. Describe exact clothing, era, and ancient materials so the AI image generator keeps strict visual continuity across all scenes (even 85+ scenes).
- Keep the same character designs locked for the entire video.

CRITICAL: You MUST write a highly detailed, expansive documentary script that is exactly {target_words} words long. Expand heavily on the narrative. Do not summarize.

CRITICAL SCENE PACING: Produce between {scene_target} and {scene_cap} scenes (at least 1 scene per {SECONDS_PER_SCENE} seconds of audio so visuals stay cinematic). Prefer closer to {scene_target}+ scenes for longer runtimes.

Word-count check: full_script (and the concatenation of all script_text fields) must be approximately {target_words} words (accept +/- 10%).

Return a JSON object with keys: title, full_script, style, scenes.
Each scene object must include: scene_id, script_text, visual_prompt, keywords, duration.
Set style to "{style.value}" and every scene duration to 0.
Distribute narration evenly across scenes so each scene has substantial script_text.
"""
