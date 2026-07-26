"""Prompt templates for documentary narration + generative visual prompts."""

from __future__ import annotations

import math
import re

from youtube_pipeline.models import AspectRatio, VisualStyle

STYLE_GUIDANCE: dict[VisualStyle, str] = {
    VisualStyle.CINEMATIC: (
        "Cinematic storytelling: dramatic lighting, shallow depth of field, "
        "widescreen composition, rich color grading, slow purposeful pacing. "
        "Write narration that hooks viewers in the first sentence, builds "
        "curiosity with vivid concrete imagery, and lands an emotional payoff."
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
    """Build the global style lock prepended to every ``visual_prompt``."""
    style_value = (style.value if isinstance(style, VisualStyle) else str(style)).strip().lower()
    style_label = style_value.replace("_", " ")
    subject = " ".join((idea or "the story").strip().split())
    if len(subject) > 140:
        subject = subject[:137].rstrip() + "..."
    if style_value == "cinematic":
        head = f"(Epic cinematic portrayal of {subject}"
    else:
        head = f"(Epic cinematic {style_label} portrayal of {subject}"
    return f"{head}, hyper-detailed, {_STYLE_LOCK_MARKER})"


def ensure_visual_prompt_has_anchor(visual_prompt: str, anchor: str) -> str:
    """Prepend ``anchor`` when the LLM omitted the global style lock."""
    text = (visual_prompt or "").strip()
    if not text:
        return f"{anchor}: atmospheric establishing shot, period-accurate detail"
    if _STYLE_LOCK_MARKER in text.lower():
        return text
    compact_anchor = re.sub(r"\s+", " ", anchor).strip().lower()
    if text.lower().startswith(compact_anchor[:48]):
        return text
    return f"{anchor}: {text}"


SYSTEM_PROMPT = """You are a master documentary scriptwriter and visual prompt engineer
for an asset-generation pipeline (Edge-TTS narration + Pollinations.ai images).

You MUST return valid JSON only (no markdown fences, no commentary).

Preferred response shape — a JSON object:
{
  "title": string,
  "full_script": string,
  "style": string,
  "scenes": [
    {
      "scene_id": integer >= 0,
      "narration": string,
      "visual_prompt": string,
      "keywords": string[],
      "duration": 0
    }
  ]
}

You may also return a bare JSON array of scene objects. If you do, each object MUST
include "narration" and "visual_prompt".

Rules:
- Act as a master documentary scriptwriter: authoritative, vivid, educational,
  and expansive — never a short overview or bullet summary.
- Every scene MUST include:
  - narration: spoken voiceover text for Edge-TTS (clear, complete sentences)
  - visual_prompt: hyper-specific visual description for Pollinations.ai image generation
- scene_id values must be contiguous starting at 0 when present.
- Concatenating all narration fields (with spaces) should approximately equal full_script
  when full_script is provided.
- Expand with rich documentary detail, context, examples, and narrative beats.

CRITICAL — VISUAL CONSISTENCY & CHARACTER LOCK (every visual_prompt):
- Invent ONE global STYLE ANCHOR from the idea's era, culture, subjects, and look.
- EVERY visual_prompt MUST begin with that exact STYLE ANCHOR, then a colon,
  then the scene-specific shot. Example:
  "(Epic cinematic ancient Indian mythology, hyper-detailed, continuous character design: [scene specifics])."
- Keep characters, costumes, materials, and palette locked across all scenes.
- Do NOT use modern terms or modern objects unless the topic truly requires them.
- Describe exact clothing, era, architecture, and materials so Pollinations stays consistent.
- keywords must be era/subject continuity tags (2-6 items), not generic stock nouns.
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
    scene_target = max(min_scenes, 2)
    scene_cap = max(max_scenes, min_scenes)

    style_text = STYLE_GUIDANCE[style]
    style_anchor = build_visual_style_anchor(idea=idea, style=style)

    return f"""Write a master documentary package for this idea (asset generation only — no video edit):

IDEA: {idea}

STYLE: {style.value}
STYLE GUIDANCE: {style_text}
ASPECT RATIO: {aspect_ratio.value}
TARGET RUNTIME: {duration_seconds} seconds ({duration_seconds / 60:.1f} minutes)

GLOBAL VISUAL STYLE ANCHOR (use this EXACT prefix on EVERY visual_prompt):
{style_anchor}

CRITICAL NARRATION RULES:
- Field name is "narration" (spoken text for Edge-TTS).
- Write an expansive documentary voiceover totaling about {target_words} words (+/- 10%).
- Do not summarize. Expand with context, examples, and narrative beats.

CRITICAL VISUAL PROMPT RULES:
- Field name is "visual_prompt" (hyper-specific Pollinations.ai image prompt).
- Every visual_prompt MUST start with the GLOBAL VISUAL STYLE ANCHOR above, then ": ", then scene specifics.
- Example: "{style_anchor}: wide documentary shot of a research lab whiteboard covered in RAG retrieval diagrams, cool practical lighting, shallow depth of field."
- Keep character/subject designs locked for the entire video.

CRITICAL SCENE PACING: Produce between {scene_target} and {scene_cap} scenes
(at least 1 scene per {SECONDS_PER_SCENE} seconds). Prefer closer to {scene_target}+ for longer runtimes.

Return JSON with keys: title, full_script, style, scenes
(or a JSON array of scenes with narration + visual_prompt).
Each scene should include: scene_id, narration, visual_prompt, keywords, duration=0.
Set style to "{style.value}".
Distribute narration evenly so each scene has substantial spoken text.
"""
