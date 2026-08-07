# Dialogue format — Design

**Date:** 2026-08-06  
**Status:** Approved for planning  
**Goal:** Add a Dialogue content format (3–4 character cast, distinct voices, short scene) plus two all-format product fixes: auto duration/max-scenes, and correct 9:16 image generation.

## Problem

Quizverse shipped a first-class `format` seam. Creators next want **dialogue drama**: named characters speaking with different voices, nameplates on screen, Shorts-length scenes.

Separately, today’s create form still asks for **duration** and **max scenes** even though the script engine and format already imply length; and **Gemini image gen ignores aspect**, so 9:16 jobs often get landscape frames that are only cropped at compose time.

## Goals

1. Add `format=dialogue` beside `narrative` and `quizverse`.
2. Cast of **3–4** named roles; **auto-cast** Edge TTS voices; **studio remap** + regenerate dialogue VO.
3. Short scene target **~45–90s**; default aspect **9:16** (override allowed).
4. LLM returns `cast[]`, `lines[]`, `visual_beats[]`; TTS per line; compose with captions + soft-fail **nameplates**.
5. **All formats:** duration and max-scenes are derived automatically from format + aspect + generated script (create form no longer requires manual pick).
6. **All formats:** image generation respects job aspect (`9:16` → vertical output, not landscape-then-crop-only).

## Non-goals (v1)

- Lip-sync / talking-head video.
- Create-form per-character voice picking (studio remap only).
- User-uploaded screenplay as primary path.
- ElevenLabs-only casting.
- Auto YouTube post.
- Mid-length / feature-length dialogue episodes.

## Product rules

### Format vs style (unchanged)

| Field | Meaning |
|-------|---------|
| `format` | Structure: `narrative` \| `quizverse` \| `dialogue` |
| `style` | Visual look + BGM only |
| `aspect_ratio` | Frame: `9:16`, `16:9`, `1:1` |

### Dialogue v1 structure

**Create form**

- Format → Dialogue  
- Idea, language, style, aspect (default **9:16**)  
- **No** duration / max-scenes inputs (see All-format rules)  
- No cast voice pickers at create  

**LLM payload**

```text
title: string
cast: [{ id, name, gender_hint, voice_hint }]   # exactly 3–4
lines: [{ speaker_id, text }]                   # ~8–16 short lines
visual_beats: [{ visual_prompt, line_start, line_end }]  # ~4–6, cover all lines
```

**Audio**

- Assign each cast member an Edge TTS voice from language locale (gender/age hints).
- Synthesize each line with that voice; ~250–400ms silence between lines.
- Concatenate to `voiceover.mp3`; retain per-line timing for captions/nameplates.

**Studio**

- **Cast** panel: character → voice dropdown + preview; “Update dialogue voiceover” regenerates all lines with current mapping.
- Image HITL slots = **visual beats** (not one slot per line).

**Compose**

- One image per visual beat, held across its line range.
- Burned captions for spoken text.
- Soft-fail nameplate (speaker display name) timed to each line.
- Assemble must still produce a video if nameplates fail.

### All-format: auto duration & max scenes

Applies to **narrative**, **quizverse**, and **dialogue**.

| Format | How length is chosen |
|--------|----------------------|
| `dialogue` | Target ~45–90s from line count / spoken length; visual beat count from script (~4–6). |
| `quizverse` | Comment: beat holds already define length; Reveal: `question_count × ~20s` (+ hook/outro). |
| `narrative` | Derive target scene count from idea + aspect defaults (Shorts `9:16` → fewer/faster scenes; `16:9` → existing scene budget heuristic). Duration follows measured VO after TTS (compose already uses scene durations). |

**UI**

- Remove or hide **Duration** and **Max scenes** from the create form for all formats.
- API may keep optional `duration` / `max_scenes` for backward compatibility; if omitted (preferred), server applies format/aspect defaults. If provided, treat as soft hints only where the format already clamps (e.g. quizverse question_count still wins for quiz structure).

**Success criterion:** a new user never has to guess duration/max scenes to get a coherent Short or film.

### All-format: aspect-correct image generation

**Bug today:** `GeminiImageProvider` generates from prompt text only — no aspect config — so 9:16 jobs often receive landscape images; FFmpeg later crops with `force_original_aspect_ratio=increase`.

**Required**

1. Pass job `aspect_ratio` into image generation (provider API image size / aspect config when supported).
2. Always include an explicit aspect instruction in the image prompt (`vertical 9:16 portrait frame`, etc.).
3. After download, if pixel ratio is wrong, **center-crop (or pad) to target aspect** before saving the scene asset used by compose — so studio previews match the final frame.
4. Apply on bulk auto-fill and single-scene regenerate paths.

**Success criterion:** a 9:16 job’s studio scene thumbnails are visually vertical, not landscape letterboxed/cropped at the last second only.

## Data model (additive)

### Request

```text
format: "narrative" | "quizverse" | "dialogue"   # default narrative
# quiz fields unchanged when format=quizverse
# duration / max_scenes optional (auto when omitted)
```

### Script / scenes

- Extend `SceneData` (or parallel structures persisted in run dir) with:
  - `speaker_id` / `speaker_name` (dialogue lines / beats)
  - `cast` + `voice_map` persisted as `cast.json` / `voice_map.json`
  - `lines` timing sidecar for nameplates (or embed in `script_timed.json`)
- Visual beats expand into linear `SceneData` rows for HITL (one scene_id per beat), with line ranges stored in metadata.

### Workspace

```text
format, aspect_ratio
cast: [{ id, name, voice_id, voice_label }]
# existing scenes[] = visual beats for dialogue
```

## Pipeline impact

| Stage | Change |
|-------|--------|
| Generator | Branch `format=dialogue`; validate cast/lines/beats; auto voice assign |
| TTS | Multi-voice per-line synth + concat + timings |
| Orchestrator | Persist cast/voice_map; auto scene budget when duration/max_scenes omitted |
| Image provider | Aspect-aware generate + normalize |
| Composer | Nameplate overlays by line timing; captions unchanged path |
| API / frontend | Format=Dialogue; hide duration/max scenes; Cast panel in studio |

## Testing

- Unit: dialogue expand beats; voice map remap regen; aspect normalize crop.
- Generator: mocked LLM cast/lines/beats validation + retries.
- TTS: multi-voice concat duration ≈ sum(line) + gaps.
- Image: 9:16 request yields asset with portrait aspect (within tolerance).
- E2E smoke: dialogue job → waiting_for_assets with beat count; narrative/quizverse still default when format omitted.
- Regression: existing narrative generate without duration/max_scenes still works.

## Rollout

1. Spec → implementation plan (SDD).  
2. Ship aspect image fix + auto duration/max-scenes early if they unstick Quizverse Shorts UX.  
3. Dialogue format behind same create-form Format dropdown.  
4. Deploy via `main` / Render as usual.
