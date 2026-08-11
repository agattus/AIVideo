# YouTube SEO Pack Design

**Date:** 2026-08-09  
**Status:** Approved (Approach 1)  
**Branch:** `feat/dialogue-format`

## Problem

Every video currently gets nearly the same YouTube description and hashtags from a frontend template (`YouTubeReachGuide.tsx`). Titles sometimes fall back to the raw idea string. That packaging does not help the YouTube algorithm or encourage shares.

## Goals

- Unique, SEO-minded **title + description + tags + hashtags + pinned comment** per video
- Mode-aware:
  - **Shorts** when `aspect_ratio == "9:16"`
  - **Long-form** otherwise
- **Bilingual:** primary copy in script language; English keywords/hashtags for discovery
- Full pack: primary title, 2–3 alt titles, description, tags, hashtags, pinned comment, chapters (long-form only)
- Soft-fail: never block Phase 1 if packaging LLM fails

## Non-goals

- Automatic YouTube upload / Data API
- Rewriting the film script itself for SEO
- Thumbnail text generation (existing stills flow stays)

## Approach

**LLM packaging pass after script is ready** (Approach 1).

One structured LLM call produces `youtube_metadata.json` from script + request context. Studio exposes copy-ready fields and a regenerate action.

## Data model

File: `{run_dir}/youtube_metadata.json`

```json
{
  "mode": "shorts | longform",
  "language": "en | te | …",
  "primary_title": "…",
  "alt_titles": ["…", "…"],
  "description": "…",
  "tags": ["…"],
  "hashtags": ["#…"],
  "pinned_comment": "…",
  "chapters": [{"start_seconds": 0, "label": "…"}],
  "source": "llm | fallback",
  "generated_at": "ISO-8601"
}
```

Constraints:

| Field | Shorts | Long-form |
|-------|--------|-----------|
| `primary_title` | ≤70 chars | ≤100 chars |
| `alt_titles` | 2–3 | 2–3 |
| `description` | ~800–1200 chars | ~1500–2500 chars preferred |
| `tags` | 8–15 | 10–20 |
| `hashtags` | 3–8 (include `#shorts` when Shorts) | 3–8 (no forced `#shorts`) |
| `chapters` | `[]` | 3–8 beats when duration known; else scene-based labels |
| `pinned_comment` | 1 engaging question / CTA | same |

## Generation rules (prompt contract)

- Curiosity-gap title; concrete noun + tension; no false clickbait; no ending spoilers
- First 100 chars of description = hook + primary keyword
- Description structure: hook → 1–2 sentence synopsis (no spoiler) → bullet value props → CTA → English keyword line → hashtags
- Tags: mix of specific story terms + category terms; language-aware
- Bilingual: title/desc body in `script.language` (or request language); add an English keyword line near the end of description
- Prefer uniqueness vs prior jobs when idea is similar (include idea + title + first/last scene cues in prompt)

## Pipeline integration

1. After script (+ optional timing) is available in Phase 1 — prefer after TTS so chapter times can use real durations when present
2. Call `generate_youtube_pack(script, request, *, timed_script=None)`
3. Write `youtube_metadata.json`
4. Soft-fail on LLM/parse errors → write story-specific **fallback** pack (not the old generic template)
5. On quality **regen-script**, regenerate pack after new script/TTS
6. Do **not** gate assemble on pack presence

Fallback pack (no LLM):

- Title: script title (trimmed to mode limit); alts = light variants of title/idea
- Description: title + idea + first 2–3 scene narrations summarized + CTA + English keyword line from idea + mode hashtags
- Tags: tokenized keywords from title/idea/scene keywords
- Chapters: from scene start times if timed; else empty for Shorts

## API

- Workspace includes `youtube_pack` (contents of `youtube_metadata.json` or `null`)
- `POST /api/v1/jobs/{job_id}/youtube-pack/regenerate` → regenerate and return pack
- No separate edit API in v1 (copy-only); optional later

## Frontend

- Port/wire `YouTubeReachGuide` in worktree (or JobStudio YouTube panel) to prefer server `youtube_pack`
- Copy buttons: primary title, each alt, description, tags (comma-joined), hashtags, pinned comment, chapters (YouTube chapter format)
- **Regenerate pack** button
- Remove hardcoded “(you won't believe the ending)” suffix and static hashtag block when pack exists
- Title step / desc step auto-done when pack exists (or fallback written)

## Module layout

```
src/youtube_pipeline/seo/
  __init__.py
  models.py      # Pydantic YoutubePack
  prompts.py     # system/user prompts
  generator.py   # LLM + fallback
  store.py       # load/save youtube_metadata.json
```

## Tests

- Unit: fallback pack uniqueness from different scripts
- Unit: mode selection from aspect ratio
- Unit: title length clamps
- Unit: LLM JSON → validated `YoutubePack`
- API: regenerate endpoint writes file and returns pack
- Frontend optional: pack fields render when workspace has `youtube_pack`

## Success criteria

- Two different jobs never share an identical description body
- Shorts packs include `#shorts`; long-form packs include chapters when timing exists
- Phase 1 completes even if packaging LLM fails
- Studio can copy a full upload pack in one panel

## Out of scope follow-ups

- Persist user-edited pack fields
- A/B title experiment tracking
- Auto-upload to YouTube
