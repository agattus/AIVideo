# Shot-synced stills (engaging cuts) — Design

**Date:** 2026-08-06  
**Status:** Approved for planning  
**Goal:** Make films feel shot-by-shot and less static using free still images + motion, while letting the creator choose video duration. Max scenes stay auto-derived from the script/dialogue.

## Problem

Dialogue jobs often land ~4–6 visual beats for a ~1-minute film, so one still holds across many spoken lines and feels static. Creators want denser, VO-synced shots. True AI video (Veo/Kling/Runway) is out of scope for a **$0** budget (no free API tier). Separately, creators want to **choose duration** again; max scene count should still follow the generated script rather than a manual scene spinner.

## Goals

1. **Dialogue:** one visual scene / one image **per dialogue line**, timed to that line’s measured VO (+ short inter-line gap).
2. **Narrative & Quizverse:** denser auto scene budgets scaled from the creator’s chosen duration; prompts encourage short, distinct shots (avoid long single-image holds).
3. **Create UX:** restore **manual duration**; keep **max scenes automatic** from format + duration + script/dialogue structure.
4. **Compose:** varied Ken Burns per scene and snappier crossfades so stills feel more like edited shots.
5. Stay on existing free/cheap image providers (Gemini free tier / Pollinations / OpenAI images as configured). No AI video generation.

## Non-goals (v1)

- Veo / Kling / Runway / other text-to-video or image-to-video APIs.
- Lip-sync or talking-head generation.
- Manual max-scenes control on the create form.
- Changing Dialogue cast / multi-voice TTS / nameplates (already shipped).
- Guaranteeing Gemini free-tier quota for high shot counts (soft-fail / retry best-effort).

## Product rules

### Length controls

| Control | Behavior |
|---------|----------|
| `duration` | **Creator-selected** on create (all formats). Soft target for script + auto scene budget. |
| `max_scenes` | **Auto only.** Derived from format + duration (+ quiz fields); Dialogue scene count ultimately follows line count after expand. Hidden from create form. |

### Shot structure

**Dialogue**

- LLM may still emit high-level beat ideas, but the expander **materializes one `SceneData` per line** (`line_start == line_end == i`).
- Each scene has its own `visual_prompt` (derived from line + context; not a single reused group prompt).
- TTS timing already per-line; scene duration = that line’s speech (+ gap policy unchanged).
- Nameplates + captions unchanged.

**Narrative**

- Auto `max_scenes` scales up with longer duration (more cuts per minute than today’s sparse defaults).
- Script prompts require distinct visual prompts per scene and discourage “one establishing shot for the whole act.”

**Quizverse**

- Preserve Comment / Reveal beat grammar.
- Auto scene budget still driven by quiz mode + question count; when duration is provided, clamp/scale scene density so longer targets don’t leave long static holds between quiz beats where the format allows extra B-roll/narration scenes.

### Motion / engagement

- Ken Burns: vary zoom direction/amount per scene (deterministic from `scene_id`), avoid identical push-in on every shot.
- Crossfade: slightly shorter default for dialogue and short-form aspect (`9:16`) so cuts read faster.
- Still images remain the media type (`scene_XX.jpg`); motion is compose-time only.

### Studio / pipeline

- Phase 1: script → TTS → prompts (Dialogue cast/lines/voice_map unchanged).
- Auto-fill: one image per scene (Dialogue ≈ one per line).
- Studio: per-scene regenerate/upload; cast voice remap unchanged.
- Soft-fail: one failed image gen should not necessarily fail the whole job when a prior asset or retry path exists; surface clear per-scene errors in workspace.

## API / schema notes

- `GenerateVideoRequest.duration` required-or-defaulted as a visible user field again (keep API optional with a sensible default if omitted for backward compatibility).
- `max_scenes` remains optional/omitted from UI; server fills via `resolve_auto_scene_budget` then Dialogue expand may raise scene count to `len(lines)`.
- No new format enum values.

## Success criteria

1. Dialogue job with N lines yields N studio scenes / N images (after successful autofill).
2. Each Dialogue scene’s on-screen duration matches its line VO window (within existing pause/timing tolerance).
3. Create form shows duration; does not show max scenes.
4. Narrative job at longer duration requests a higher auto `max_scenes` than a short one.
5. Assembled Shorts show varied Ken Burns (not identical zoom on every scene).
6. Regression: Quizverse Comment/Reveal timing + Narrative assemble still pass existing smoke tests.

## Implementation sketch (for planning)

1. Dialogue expander / generator: per-line scenes + per-line visual prompts; update prompts/schema/tests.
2. `resolve_auto_scene_budget`: take creator duration as primary; raise narrative density; dialogue max_scenes ≥ expected line band.
3. Frontend: restore duration control; keep max scenes hidden; rebuild `web/`.
4. FFmpeg Ken Burns + crossfade tuning for short-form / dialogue.
5. Tests: dialogue expand count == lines; budget scales with duration; compose filter variation smoke.

## Out of scope follow-ups

- Paid Veo provider behind a future `ASSET_PROVIDER=veo` (or similar) when budget allows.
- Stock footage provider revival as an alternate free motion path.
