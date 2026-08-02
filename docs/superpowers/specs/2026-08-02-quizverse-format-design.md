# Quizverse format — Design

**Date:** 2026-08-02  
**Status:** Approved for planning  
**Goal:** Add a Quizverse content format alongside narrative films — Shorts that drive comments without revealing answers, and long-form quizzes with timed reveals.

## Problem

S-Studio only produces **single-narrator narrative** videos. “Style” (cinematic, shorts, etc.) changes visuals/BGM, not structure. Creators want engaging quiz formats:

- **Shorts:** ask a question, build tension, push viewers to comment; creator answers in comments the next day.
- **Long form:** several questions with on-screen timer and answer reveal; runtime scales with question count.

## Goals

- Introduce a first-class **`format`** field: `narrative` (default) | `quizverse`.
- Keep existing narrative pipeline unchanged when `format=narrative`.
- Quizverse **Comment mode** (Shorts-oriented): no in-video answer; comment CTA; draft pinned/community text for the creator.
- Quizverse **Reveal mode** (long-form): per question **5s question → 10s timer → 5s reveal+explain** (~20s/question).
- Structured quiz script (not one continuous narration blob).
- Burned-in overlays: question card, countdown, answer slam **or** comment CTA.
- TTS speaks only what belongs in that mode (question + CTA, or question + reveal/explain).
- Create-form UX to pick format, mode, and question count.

## Non-goals (v1)

- Dialogue drama / multi-character speaking formats (later).
- Auto-posting answers to YouTube comments or Community posts.
- Live multiplayer / scoring / leaderboards.
- User-uploaded quiz JSON as the primary path (LLM-generated from idea is primary).
- Changing the meaning of visual `style` to mean format (keep them separate).

## Product rules

### Format vs style

| Field | Meaning | Examples |
|-------|---------|----------|
| `format` | Content structure / pacing | `narrative`, `quizverse` |
| `style` | Visual look + BGM bed | `cinematic`, `fast_paced_shorts`, … |
| `aspect_ratio` | Frame | `9:16` Shorts, `16:9` long |

### Modes

#### Comment mode (Shorts)

Default `question_count=1` (clamp 1–5). Structure:

1. **Hook** once (~1–2s) — spoken teaser / on-screen sting  
2. For each question:  
   - **Question** (~3–4s) — big question card + VO  
   - **Think / timer** (~3–5s) — countdown UI (shorter than long-form; not 10s)  
3. **CTA** once at end (~2–3s) — “Drop your answers in the comments — I reply tomorrow”

- **Answer must not** appear on screen, in captions, or in VO.
- Answer + short explain are stored for **studio only** (creator cheat sheet / next-day replies).
- Studio generates **draft pinned/community comment** text the creator can copy (includes all answers for the creator’s paste-later post, not shown in the video).

#### Reveal mode (long form)

Per question (~20s):

| Beat | Duration | On screen | VO |
|------|----------|-----------|-----|
| Question | 5s | Question (+ optional A/B/C/D) | Reads question |
| Timer | 10s | Countdown 10→0 | Minimal / tick bed (no answer) |
| Reveal | 5s | Answer slam + 1–2 line explain | Reads answer + explain |

- `question_count` N → target runtime ≈ `N × 20s` (+ short intro/outro ≤ ~6s total).
- Default aspect `16:9` unless user overrides.
- Suggested N range: 3–15 (clamp in API).

## Data model

### Request (`PipelineRequest` / `GenerateVideoRequest`)

```text
format: "narrative" | "quizverse"   # default narrative
quiz_mode: "comment" | "reveal"     # required when format=quizverse; ignored otherwise
question_count: int                 # Comment default 1; Reveal default 5; clamp by mode
```

Existing: `idea`, `style`, `aspect_ratio`, `language`, `voice`, `duration` / `max_scenes`.

- For Quizverse Reveal: prefer deriving scene/beat budget from `question_count`, not from `duration` (duration may be informational or derived).
- For Comment mode: force or strongly default `aspect_ratio=9:16` in the UI (API may still accept override).

### Script package

Extend script JSON with quiz structure while keeping a linear `scenes[]` list the assemble path can consume.

**v1 approach:** LLM returns `questions[]`; generator expands each question into beats. Each beat is a `SceneData` with:

```text
beat_type: "hook" | "question" | "timer" | "reveal" | "cta" | "intro" | "outro"
quiz_index: int          # 0-based question index (for question/timer/reveal/cta)
question: str            # display text (question beats)
choices: list[str]       # optional, max 4
answer: str              # stored always; only rendered/spoken on reveal beats
explain: str             # short; reveal only
hold_seconds: float      # authoritative beat length (5 / 10 / 5 / …)
script_text: str         # what TTS speaks for this beat (may be empty on timer)
visual_prompt: str       # still image for the beat
```

Narrative jobs omit these fields (defaults / unused). Composer and TTS branch on `format` + `beat_type`.

### Studio extras

- `quiz_answer_key`: list of `{quiz_index, question, answer, explain}` for Comment mode (and Reveal as reference).
- `community_post_draft`: string for Comment mode (copy button in JobStudio).

## Pipeline

```text
GenerateForm (format + mode + N)
        ↓
ScriptEngine (format-specific prompts + JSON schema)
        ↓
scenes[] beats with hold_seconds
        ↓
TTS: speak script_text per beat; silence/hold for timer beats
        ↓
Compose: Ken Burns stills + overlays (question / countdown / reveal or CTA)
        ↓
Mux VO + BGM + light SFX (tick / whoosh / sting)
```

### Script engine

- New prompt pack for Quizverse (not thriller-documentary narration rules).
- JSON schema requires `questions[]` (question, choices?, answer, explain); generator expands to beats:
  - Comment: hook + N × (question + timer) + cta (no reveal beats).
  - Reveal: optional intro + N × (question + timer + reveal) + optional outro.
- Validate: no answer text leaked into Comment-mode `script_text` or burn-in display fields.

### TTS

- Reuse per-scene/per-beat Edge TTS + pause logic.
- Timer beats: no speech (or optional soft “time’s up” at end of Reveal timer only — v1: silence during countdown).
- Comment CTA beat: spoken CTA line.
- Voice: single narrator voice (same picker as today).

### Compose overlays

- **Question card:** large readable text (Shorts-safe margins).
- **Timer:** numeric countdown synced to `hold_seconds` (Reveal 10s; Comment 3–5s).
- **Reveal:** answer emphasis + explain line.
- **CTA:** comment prompt end card.
- Captions: sync to spoken beats only; do not caption the hidden answer in Comment mode.

### SFX (soft-fail)

- Timer: light tick / pulse if pack has a suitable cue; else silent.
- Reveal: whoosh or sting.
- Missing file → skip (existing soft-fail pattern).

## API / UI

### Create form

- Format toggle: Narrative | Quizverse.
- If Quizverse: Mode Comment | Reveal; Question count stepper.
- Comment mode: suggest 9:16; Reveal: suggest 16:9.
- Idea placeholder changes (e.g. “Greek gods quiz for Shorts”).

### Job studio

- Show quiz answer key when format is Quizverse.
- Comment mode: **Copy community / pinned comment draft**.
- Assemble / voice / images flow unchanged at the job level.

### Status / library

- Optional badge: `Quizverse · Comment` / `Quizverse · Reveal` on job cards (nice-to-have; not blocking).

## Error handling

- LLM returns answer inside Comment-mode spoken fields → strip / regenerate that beat.
- `question_count` out of range → clamp with warning in logs.
- Overlay render failure → assemble continues with VO + stills (log warning), same soft-fail spirit as captions.

## Testing

- Unit: beat expansion (Comment vs Reveal timings sum correctly).
- Unit: Comment mode never includes answer in TTS text or caption cues.
- API: generate request accepts `format` / `quiz_mode` / `question_count`.
- Compose smoke: one Comment Short + one 2-question Reveal job produce overlays without crash.

## Rollout

1. Schema + prompts + beat expansion (Phase 1 script only can pause in studio).
2. TTS + compose overlays + create-form UX.
3. Studio answer key + community draft.
4. Deploy; narrative default ensures no regression.

## Success criteria

- Creator can generate a Comment-mode Short that never reveals the answer on video.
- Creator can generate a Reveal-mode film whose length tracks `question_count × ~20s`.
- Narrative jobs behave exactly as before when format is omitted or `narrative`.
