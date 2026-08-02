# Scene ambience + SFX (bundled pack) — Design

**Date:** 2026-08-01  
**Status:** Approved for planning  
**Goal:** Make films feel alive with soft per-scene ambience beds plus occasional one-shot cues (e.g. rain + thunder), without paid SFX APIs.

## Problem

Today the mix is voiceover + a single music BGM bed. Narration can mention rain, cities, forests, etc., but the soundtrack never reacts — so cuts feel flat compared to Flow-style storytelling.

## Goals

- Per-scene **ambience loop** under the narration (soft).
- Up to **two timed one-shots** per scene (e.g. thunder at 40% into the scene).
- Bundled **offline CC0 pack** — no network dependency for SFX.
- Soft-fail: missing SFX file skips that layer; assemble still succeeds.
- Keep existing BGM + VO mix behavior; SFX is an additive layer.
- Studio can preview tags and override ambience before Assemble (v1).

## Non-goals

- AI-generated Foley or paid SFX APIs.
- Custom user-uploaded SFX files in v1.
- Precise word-level alignment of one-shots to spoken words (scene-fraction timing only).
- Replacing the music BGM with ambience.

## Architecture

```text
ScriptEngine → scenes with ambience + sfx[]
        ↓
Keyword fallback if tags missing
        ↓
Assemble (FFmpeg):
  VO (1.0) + BGM (~0.10) + ambience timeline (~0.12) + one-shots (~0.35)
```

### Bundled pack layout

```text
assets/sfx/
  LICENSE.txt                 # sources + CC0 notes
  ambiences/
    rain.mp3
    wind.mp3
    forest.mp3
    city.mp3
    ocean.mp3
    fire.mp3
    night.mp3
    room.mp3
  oneshots/
    thunder.mp3
    footsteps.mp3
    door.mp3
    birds.mp3
    crowd_cheer.mp3
    whoosh.mp3
```

Loops should be short seamless (or long enough to `aloop`) mono/stereo MP3s, kept small for git.

### Scene schema (additive)

On each scene (script JSON / prompts / domain model):

| Field | Type | Notes |
|-------|------|--------|
| `ambience` | string | One of pack ambience tags, or `none` |
| `sfx` | list | `[{ "tag": "<oneshot>", "at": 0.0–1.0 }]` — max 2; `at` clamped to `0.15–0.85` |

Unknown tags are ignored at mix time (soft-fail).

### Tagging

1. **LLM:** Script prompts ask for `ambience` + optional `sfx` consistent with narration/visuals.
2. **Fallback:** If absent/invalid, keyword map on `script_text` + `visual_prompt` (e.g. rain/storm → `rain` + optional `thunder`; forest/jungle → `forest`; city/street → `city`; ocean/sea/beach → `ocean`; fire/campfire → `fire`; night/midnight → `night`; wind/stormy → `wind`; default indoor → `room` or `none`).

### Mix (FFmpeg)

Extend the existing mux path in `ffmpeg_composer.py`:

1. Build a silent base equal to VO duration (or use VO as duration master).
2. For each scene with ambience ≠ `none`, schedule a looped clip for that scene’s time range with ~0.3s fade in/out.
3. For each one-shot, `adelay` to `scene_start + at * scene_duration`.
4. `amix` VO + BGM + ambience bus + oneshot bus with volumes above.
5. Missing pack file → log warning, omit that input.

Starting volumes (tunable via env later if needed):

- Voiceover: `1.05` (match current)
- BGM: `0.10` (match current)
- Ambience: `0.12`
- One-shots: `0.35`

### Studio (v1)

- Scene card shows `ambience` and listed `sfx` tags.
- Dropdown to change ambience (writes into workspace / script sidecar before assemble).
- No oneshot editor in v1 (regenerate script or accept LLM/fallback).
- Assemble uses the latest tags from the workspace.

### API / workspace

- Expose ambience/sfx on workspace scene slots (same as script).
- Optional: `PATCH` or small POST to update scene ambience — keep minimal (reuse script.json / prompts.json write helper).

## Error handling

| Case | Behavior |
|------|----------|
| Unknown ambience/sfx tag | Treat as none / skip cue |
| Missing mp3 on disk | Skip layer; log warning |
| Scene has `ambience=none` and empty `sfx` | No SFX layer (VO+BGM only) |
| Pack directory absent | Assemble behaves as today (VO±BGM) |

## Testing

- Unit: keyword fallback mapping.
- Unit: filter-graph / timeline builder with fake paths (no real ffmpeg if possible); or subprocess with tiny fixtures.
- Schema: scenes accept new fields without breaking old scripts (default `none` / `[]`).
- No network required.

## Success criteria

1. A rain-heavy narration scene gets a rain bed (and optionally thunder) in the final MP4.
2. Films without matching keywords still assemble (neutral/none).
3. Overriding ambience in Studio changes the next Assemble mix.
4. Pack is CC0-documented and works offline.

## Implementation sketch (files)

| Area | Likely touch |
|------|----------------|
| Pack | `assets/sfx/**`, `LICENSE.txt` |
| Models / schema | `models.py`, script schema, prompts export |
| LLM prompts | `script_engine/prompts.py` |
| Fallback | new `audio/sfx_tags.py` or similar |
| Compose | `video/ffmpeg_composer.py` |
| Workspace / API | `hitl_workspace.py`, `api/schemas.py`, `api/main.py` |
| UI | `JobStudio.tsx`, types |
| Tests | new sfx + composer tests |
