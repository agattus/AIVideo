# Gemini image auto-fill (hybrid HITL) — Design

**Date:** 2026-08-01  
**Status:** Approved for planning  
**Goal:** Stop the copy → Google Flow → upload loop for most scenes, while keeping Flow/manual override.

## Problem

After Phase 1 (script + voice), the studio pauses at `waiting_for_assets`. Users copy each visual prompt into Google Flow (Gemini Plus), generate stills, then upload them back. Google Flow has no public API, so that path cannot be fully automated. Gemini image generation via the Gemini API can fill the same scene slots automatically.

## Goals

- Auto-generate scene stills with Gemini as soon as Phase 1 reaches `waiting_for_assets`.
- Keep hybrid overrides: regenerate, copy prompt / open Flow, replace via upload.
- Do **not** auto-assemble; user reviews then Assemble.
- Reuse existing workspace paths (`assets/scene_XX.jpg`) and Studio upload/assemble flow.
- Fail soft: missing key or per-scene errors must not wipe script/audio progress.

## Non-goals

- Automating Google Flow via browser scripting (fragile / ToS risk).
- Changing script/TTS/assemble pipeline behavior beyond post-prompt image fill.
- Multi-provider A/B in the UI (Pollinations/OpenAI remain available via env, not the default product path).

## Architecture

```text
Phase 1: idea → script → TTS → prompt pack
              ↓
   if ASSET_PROVIDER != manual:
       auto_fill_scene_images(job_id)  # configured provider → scene_XX.jpg
              ↓
   status stays waiting_for_assets
              ↓
Studio: preview / regenerate / Flow override / upload
              ↓
Assemble (existing)
```

Auto-fill calls `build_asset_provider()` so `gemini_image` (product default), `imagen` (alias), `pollinations`, and `openai_image` all work. Product UX and docs assume Gemini.

### Provider

- Add `GeminiImageProvider` implementing the existing asset provider protocol.
- Settings:
  - `ASSET_PROVIDER=gemini_image` as the documented default in `.env.example` and Render (existing local envs with `pollinations` keep working until changed).
  - `imagen` remains a **supported alias** that resolves to the same provider (backward-compatible with reserved enum).
  - `GEMINI_IMAGE_MODEL` (default: `gemini-2.5-flash-image` — Gemini native image / “Nano Banana” family; [image generation docs](https://ai.google.dev/gemini-api/docs/image-generation)).
  - Reuse `GEMINI_API_KEY`.
- `ASSET_PROVIDER=manual`: skip auto-fill (current external-tool workflow).

### Auto-fill step

Triggered at end of Phase 1 in the same worker/thread path that today pauses for assets:

1. Load scene prompts from the job workspace / prompt pack.
2. For each scene without a ready image, call the configured provider with the visual prompt plus style/aspect hints from the job request.
3. Write `assets/scene_XX.jpg` via the same helpers used by scene upload.
4. Publish static files so Studio can preview.
5. Concurrency: sequential for v1 (simplest rate-limit behavior); optional pool of 2 later if needed.
6. On per-scene failure: leave slot empty, record a short error for that scene, continue.
7. Job status remains `waiting_for_assets` even if all scenes succeed.

### Progress

- While filling, update job stage/progress messages (e.g. “Generating scene 3/8”) so Studio polling shows activity.
- Prefer extending existing status fields over inventing a new top-level status enum value for v1.

## API

Thin endpoints wrapping the same save path as upload:

| Method | Path | Behavior |
|--------|------|----------|
| `POST` | `/api/v1/jobs/{job_id}/scenes/{scene_id}/generate` | Regenerate one scene with Gemini |
| `POST` | `/api/v1/jobs/{job_id}/generate-images` | Fill missing scenes; `force=true` regenerates all |

Existing upload / workspace / assemble endpoints stay unchanged.

### Workspace / status (optional fields)

Per scene, when easy to add without breaking clients:

- `source`: `"gemini"` \| `"upload"` (optional)
- `error`: short string when last generate failed (optional)

## Frontend (`JobStudio`)

- Show auto-filled previews as they appear via existing poll.
- Progress copy while auto-fill runs.
- Per-scene actions: **Regenerate** · **Copy prompt** · **Open Flow** (`https://labs.google/fx/tools/flow` in a new tab + copy prompt to clipboard) · **Replace upload**.
- Global: **Regenerate all missing** · Assemble when all ready.
- Update copy that currently says “paste into Meta AI / Gemini” to describe hybrid: auto Gemini + optional Flow.
- Regenerate endpoints require a non-manual image provider; if `manual`, show upload/Flow-only actions.

## Error handling

| Case | Behavior |
|------|----------|
| Missing/invalid `GEMINI_API_KEY` | Phase 1 still completes; auto-fill skipped or fails with clear job message; slots empty |
| Per-scene API / network error | That scene empty + error; others continue |
| Safety block | Scene error: blocked; user edits prompt / uploads / Flow |
| `ASSET_PROVIDER=manual` | No auto-fill; prior UX |

## Config / deploy

- `.env.example` and Render env: document `ASSET_PROVIDER=gemini_image`, `GEMINI_IMAGE_MODEL`, require `GEMINI_API_KEY`.
- Render deploy already has `GEMINI_API_KEY`; set `ASSET_PROVIDER=gemini_image` there after ship.

## Testing

- Unit: `GeminiImageProvider` extracts image bytes from a mocked Gemini `generate_content` response.
- API/integration: generate-one and generate-missing fill workspace slots (mocked provider).
- No live Google API calls in CI.
- Keep existing HITL upload/assemble tests green.

## Implementation sketch (files)

| Area | Likely touch |
|------|----------------|
| Settings / enum | `config/settings.py`, `.env.example` |
| Provider | `src/youtube_pipeline/assets/gemini_image.py` (new), `factory.py` |
| Auto-fill + HITL | `hitl_workspace.py`, `tasks.py` / orchestrator pause path |
| API | `api/main.py`, `api/schemas.py` |
| UI | `JobStudio.tsx`, `client.ts`, `types.ts`, progress copy |
| Tests | new provider + API tests |

## Success criteria

1. New job with `ASSET_PROVIDER=gemini_image` and a valid key fills scene slots without leaving the app.
2. User can replace any scene via upload or regenerate; Assemble works as today.
3. Flow remains a one-click override path, not required for every scene.
4. Manual provider still supports full external-tool workflow.
