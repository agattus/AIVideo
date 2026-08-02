"""Prompt templates for thriller / dark-documentary narration + generative visuals."""

from __future__ import annotations

import math
import re

from youtube_pipeline.models import AspectRatio, VisualStyle

STYLE_GUIDANCE: dict[VisualStyle, str] = {
    VisualStyle.CINEMATIC: (
        "Cinematic storytelling: dramatic lighting, shallow depth of field, "
        "widescreen composition, rich color grading, fast purposeful scene changes."
    ),
    VisualStyle.DOCUMENTARY: (
        "Documentary realism: natural light, observational framing, "
        "authentic locations, understated color, fast-paced cuts."
    ),
    VisualStyle.CORPORATE: (
        "Corporate polish: clean modern offices, confident talent, "
        "bright balanced lighting, brand-safe color, brisk professional pacing."
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
# Soft floor used only when max_scenes is unset/too low for the runtime.
SECONDS_PER_SCENE = 8
MAX_WORDS_PER_SCENE = 20
_STYLE_LOCK_MARKER = "continuous character design"


def compute_target_words(duration_seconds: int) -> int:
    """Legacy duration-based word budget (prefer ``compute_scene_word_budget``)."""
    return max(80, int((max(1, duration_seconds) / 60) * WORDS_PER_MINUTE))


def compute_scene_word_budget(target_scenes: int) -> int:
    """Total narration words for fast-paced scenes (~18 words each)."""
    return max(40, int(target_scenes) * 18)


def compute_min_scenes(duration_seconds: int) -> int:
    """Minimum scene count for fast pacing (~one scene per 8 seconds)."""
    return max(2, int(math.ceil(max(1, duration_seconds) / SECONDS_PER_SCENE)))


def compute_target_scenes(*, max_scenes: int, duration_seconds: int) -> int:
    """Exact scene count the LLM must produce.

    Prefer the caller's ``max_scenes``. Raise to the fast-pacing floor when the
    requested cap would leave visuals lingering too long.
    """
    floor = compute_min_scenes(duration_seconds)
    return max(2, int(max_scenes), floor)


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


def build_system_prompt(target_scenes: int, *, language: str = "en") -> str:
    """System instructions with thriller narration rules + hard scene-count constraints."""
    from youtube_pipeline.i18n import normalize_language, script_language_name

    n = max(2, int(target_scenes))
    lang = normalize_language(language)
    lang_name = script_language_name(lang)
    return f"""You are a master writer of gripping Netflix-style supernatural drama and
dark thriller documentaries — and a visual prompt engineer for an asset-generation
pipeline (Edge-TTS narration + Pollinations.ai images).

Your narration must sound like a supernatural thriller or dark mystery documentary,
NOT a Wikipedia article, encyclopedia entry, or dry educational lecture.

NARRATION LANGUAGE (NON-NEGOTIABLE):
- Write EVERY `narration` field, the `full_script`, and the `title` in {lang_name}.
- Use the natural writing system / script for {lang_name} (not transliteration into Latin letters).
- Do NOT mix English into narration unless the topic truly requires a proper noun.
- Keep `visual_prompt` and `keywords` in English (image models understand English best).

You MUST return valid JSON only (no markdown fences, no commentary).

Preferred response shape — a JSON object:
{{
  "title": string,
  "full_script": string,
  "style": string,
  "scenes": [
    {{
      "scene_id": integer >= 0,
      "narration": string,
      "visual_prompt": string,
      "keywords": string[],
      "duration": 0,
      "ambience": "none" | "rain" | "wind" | "forest" | "city" | "ocean" | "fire" | "night" | "room",
      "sfx": [{{"tag": "thunder" | "footsteps" | "door" | "birds" | "crowd_cheer" | "whoosh", "at": number 0.15..0.85}}]
    }}
  ]
}}

You may also return a bare JSON array of scene objects. If you do, each object MUST
include "narration" and "visual_prompt".

HARD SCENE COUNT (NON-NEGOTIABLE):
- You MUST generate exactly {n} scenes.
- The "scenes" array length MUST be exactly {n}. Never fewer. Never more.
- scene_id values must be contiguous integers 0..{n - 1}.

NARRATION RULES (NON-NEGOTIABLE — for every scene's `narration` field):
1. The Cold Open: Start the very first scene with a dark, mysterious, or shocking hook. Do not introduce the main topic immediately. Make the audience ask 'What is happening?'
2. The Tone: The narration must be intense, suspenseful, and atmospheric. Use sensory words (e.g., 'deafening silence', 'shadows creeping', 'ancient blood' — expressed naturally in {lang_name}).
3. The Pacing: Use extremely short, punchy sentences. Use ellipses (...) to force dramatic pauses for the TTS engine.
4. The Escalation: Build the tension scene by scene. Treat the subject matter like a supernatural thriller where the stakes are life and death.
5. The Climax: End the final scene with a powerful, lingering cliffhanger or a profound, haunting realization.

LENGTH / CUT RULES (still apply):
- Each scene's `narration` MUST be incredibly concise—maximum 15 to 20 words per scene
  (ellipses count as pause marks, not filler).
- If the narration is longer than 20 words, you must split the concept into a new
  scene with a new `visual_prompt`.
- Never let a single visual linger for more than 2 short sentences.
- Prefer 1 short punchy sentence per scene. Two short sentences max.

Other rules:
- Every scene MUST include:
  - narration: spoken voiceover text for Edge-TTS in {lang_name} (thriller voice, SHORT sentences, ellipses for pauses)
  - visual_prompt: hyper-specific visual description for image generation (ENGLISH)
- Concatenating all narration fields (with spaces) should approximately equal full_script
  when full_script is provided.
- Cover the topic with many quick, rising beats — not long monologues over one image.

CRITICAL — VISUAL CONSISTENCY & CHARACTER LOCK (every visual_prompt):
- Invent ONE global STYLE ANCHOR from the idea's era, culture, subjects, and look.
- EVERY visual_prompt MUST begin with that exact STYLE ANCHOR, then a colon,
  then the scene-specific shot. Example:
  "(Epic cinematic ancient Indian mythology, hyper-detailed, continuous character design: [scene specifics])."
- Keep characters, costumes, materials, and palette locked across all scenes.
- Do NOT use modern terms or modern objects unless the topic truly requires them.
- Describe exact clothing, era, architecture, and materials so image gen stays consistent.
- Prefer dark, atmospheric, high-contrast thriller framing in visual_prompt details.
- keywords must be era/subject continuity tags (2-6 items), not generic stock nouns.

SOUND DESIGN (required for every scene):
- Set ambience to exactly one supported tag: rain, wind, forest, city, ocean, fire,
  night, room, or none. Use none when no ambience genuinely matches.
- Set sfx to an array of 0–2 supported cues. Supported tags: thunder, footsteps,
  door, birds, crowd_cheer, whoosh. Each cue is {{"tag": string, "at": 0.15..0.85}}.
- Choose ambience and cues only when they match the narration or visible action.
  Never add random sounds merely to fill the fields; use [] when no cue fits.
"""


# Default system prompt for imports/tests (exact count filled for common 8-scene jobs).
SYSTEM_PROMPT = build_system_prompt(target_scenes=8, language="en")


def build_user_prompt(
    *,
    idea: str,
    style: VisualStyle,
    aspect_ratio: AspectRatio,
    target_duration_seconds: int | None,
    max_scenes: int,
    target_scenes: int | None = None,
    language: str = "en",
) -> str:
    from youtube_pipeline.i18n import normalize_language, script_language_name

    duration_seconds = int(target_duration_seconds or 60)
    resolved_target = (
        int(target_scenes)
        if target_scenes is not None
        else compute_target_scenes(max_scenes=max_scenes, duration_seconds=duration_seconds)
    )
    word_budget = compute_scene_word_budget(resolved_target)
    lang = normalize_language(language)
    lang_name = script_language_name(lang)

    style_text = STYLE_GUIDANCE[style]
    style_anchor = build_visual_style_anchor(idea=idea, style=style)

    return f"""Write a GRIPPING Netflix-style supernatural / dark-thriller documentary package
for this idea (asset generation only — no video edit). Narration must NOT sound like Wikipedia.

IDEA: {idea}

NARRATION LANGUAGE: {lang_name} (code={lang})
- Write title, full_script, and every narration field in {lang_name} using its native script.
- visual_prompt + keywords stay in English.

STYLE: {style.value}
STYLE GUIDANCE: {style_text}
ASPECT RATIO: {aspect_ratio.value}
TARGET RUNTIME: {duration_seconds} seconds ({duration_seconds / 60:.1f} minutes)
TARGET_SCENES: {resolved_target}

=== STRICT REQUIREMENTS (READ CAREFULLY) ===
1. You MUST generate exactly {resolved_target} scenes.
2. Each scene's `narration` MUST be incredibly concise—maximum 15 to 20 words per scene.
3. If the narration is longer than 20 words, you must split the concept into a new
   scene with a new `visual_prompt`.
4. Never let a single visual linger for more than 2 short sentences.
5. Total narration across all scenes should be about {word_budget} words
   ({resolved_target} scenes × ~18 words). Do NOT write long expansive paragraphs.

NARRATION RULES (exact — apply to every `narration` in {lang_name}):
1. The Cold Open: Start the very first scene with a dark, mysterious, or shocking hook. Do not introduce the main topic immediately. Make the audience ask 'What is happening?'
2. The Tone: The narration must be intense, suspenseful, and atmospheric. Use sensory words (e.g., 'deafening silence', 'shadows creeping', 'ancient blood' — expressed naturally in {lang_name}).
3. The Pacing: Use extremely short, punchy sentences. Use ellipses (...) to force dramatic pauses for the TTS engine.
4. The Escalation: Build the tension scene by scene. Treat the subject matter like a supernatural thriller where the stakes are life and death.
5. The Climax: End the final scene with a powerful, lingering cliffhanger or a profound, haunting realization.

GLOBAL VISUAL STYLE ANCHOR (use this EXACT prefix on EVERY visual_prompt):
{style_anchor}

NARRATION FIELD:
- Field name is "narration" (spoken text for Edge-TTS) — MUST be {lang_name}.
- Keep each narration ≤ {MAX_WORDS_PER_SCENE} words.
- Intense thriller voice — short punchy lines, sensory language, ellipses for pauses.

VISUAL PROMPT FIELD:
- Field name is "visual_prompt" (hyper-specific image prompt) — MUST be English.
- Every visual_prompt MUST start with the GLOBAL VISUAL STYLE ANCHOR above, then ": ", then scene specifics.
- Example: "{style_anchor}: wide documentary shot of a research lab whiteboard covered in RAG retrieval diagrams, cool practical lighting, shallow depth of field."
- Keep character/subject designs locked for the entire video.
- Lean into dark, atmospheric, high-contrast thriller imagery.

SOUND DESIGN FIELDS:
- ambience is REQUIRED. Choose one: rain, wind, forest, city, ocean, fire, night,
  room, none. Use "none" unless the scene clearly supports another ambience.
- sfx is REQUIRED. Choose 0–2 cues that directly match narration or visible action,
  never random decoration. Each cue has a supported tag (thunder, footsteps, door,
  birds, crowd_cheer, whoosh) and an "at" position from 0.15 through 0.85.
- Use "sfx": [] when no supported cue genuinely fits.

SCENE COUNT CHECK: Before you answer, count the scenes array.
It MUST contain exactly {resolved_target} objects (scene_id 0 through {resolved_target - 1}).

Return JSON with keys: title, full_script, style, scenes
(or a JSON array of scenes with narration + visual_prompt).
Each scene should include: scene_id, narration, visual_prompt, keywords, duration=0,
ambience, and sfx.
Set style to "{style.value}".
"""


def scene_count_retry_addon(target_scenes: int, actual_scenes: int, *, language: str = "en") -> str:
    """Extra user-prompt pressure after a wrong scene count."""
    from youtube_pipeline.i18n import normalize_language, script_language_name

    n = max(2, int(target_scenes))
    lang_name = script_language_name(normalize_language(language))
    return f"""

IMPORTANT CORRECTION — YOUR PREVIOUS RESPONSE FAILED VALIDATION:
- You returned {actual_scenes} scenes but You MUST generate exactly {n} scenes.
- Keep narration / title / full_script in {lang_name} (native script, not Latin transliteration).
- Keep the Netflix supernatural / dark-thriller narration rules (cold open, intense tone,
  short punchy sentences with ellipses, escalating stakes, haunting climax).
- Each scene's `narration` MUST be incredibly concise—maximum 15 to 20 words per scene.
- If the narration is longer than 20 words, you must split the concept into a new
  scene with a new `visual_prompt`.
- Never let a single visual linger for more than 2 short sentences.
- Return ONLY valid JSON with exactly {n} scenes.
"""
