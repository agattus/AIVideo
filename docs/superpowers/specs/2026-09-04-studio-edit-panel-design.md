# Studio Edit Panel — Scene Strip + Subtitles

**Date:** 2026-09-04  
**Status:** Approved  
**Branch / worktree:** `feat/dialogue-format`  
**Related UI:** JobStudio HITL edit surface

## Problem

After Phase 1, creators can upload/regenerate scene images, change voice/BGM, and assemble — but they cannot:

1. **Reorder** scenes visually (drag beats into a better story order)
2. **Control burned-in subtitles** (on/off, size, position) before assemble

Captions are always burned with fixed styling; scene order is fixed to generation order.

## Goals

- One **Edit** panel in JobStudio with:
  - Horizontal **scene strip**: drag-reorder (whole scene: image + narration + timing), drop/replace stills
  - **Subtitle settings**: burn on/off, size S/M/L, position bottom / lower-third, preview on selected still
- Settings and order persist on the job and apply on the next **Assemble**
- Preserve existing Voice / Music / Quality / Assemble flows

## Non-goals (v1)

- Full NLE (multi-track, waveform scrub, frame trim)
- Font family / color / outline pickers
- Live preview of the full assembled MP4 before assemble
- Reordering only the picture while keeping VO locked to old indices
- Mobile-first gesture polish beyond basic drag (desktop primary)

## User flow

1. Open `/studio/:jobId` when `can_edit` (waiting_for_assets / failed / completed reopened).
2. Open **Edit** section (default open when images exist and video not yet final, or when re-editing).
3. Drag scene cards to reorder → API persists new order → strip + library grid refresh.
4. Drop an image on a card (or file picker) → same as today’s per-scene upload.
5. Select a card → detail pane (prompt, ambience, regenerate) + subtitle preview overlay on that still.
6. Tweak subtitle toggles → saved on job; preview updates immediately on the still.
7. **Assemble** uses current order + subtitle options.

## Data model

### Scene order

Persist an ordered list of scene ids (or rewrite `script.json` / timed script so `scenes[]` order is canonical).

Preferred v1 approach:

- On reorder, rewrite workspace artifacts so **array order is the timeline order**:
  - `script.json` / `script_timed.json` scenes array reordered
  - `timing.json` scenes + word windows remapped to new absolute timeline (concatenate speech/pause segments in new order)
  - Asset files stay as `scene_XX.jpg` keyed by **stable `scene_id`** (do not rename files on reorder)
  - Composer already resolves images by `scene_id`, not array index — keep that contract

Stable `scene_id` + ordered array = drag without renaming assets.

### Subtitle options (job-scoped)

Store beside the run dir, e.g. `edit_settings.json`:

```json
{
  "burn_captions": true,
  "caption_size": "m",
  "caption_position": "bottom"
}
```

| Field | Values | Maps to composer |
|-------|--------|------------------|
| `burn_captions` | bool | `FFmpegComposer.burn_captions` / request flag |
| `caption_size` | `s` \| `m` \| `l` | Font size multiplier on current `_caption_font_size()` |
| `caption_position` | `bottom` \| `lower_third` | Vertical placement in Pillow caption render |

Defaults: burn on, size `m`, position `bottom` (match today’s look).

## API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/jobs/{id}/edit-settings` | Return order summary + subtitle settings |
| `PUT` | `/api/v1/jobs/{id}/edit-settings` | Update subtitle settings only |
| `POST` | `/api/v1/jobs/{id}/scenes/reorder` | Body: `{ "scene_ids": [3,0,1,2,…] }` full permutation of existing ids |
| Existing | upload / generate scene image | Unchanged; keyed by `scene_id` |

Ownership: same `require_user` / `user_owns_job` as other job routes.

`GET workspace` should include `edit_settings` so the UI does not need an extra round-trip on load.

## Frontend (JobStudio)

### Edit section

- New collapsible **Edit** block (Syne/DM Sans, existing tokens — no purple/cream cliché redesign).
- **Scene strip**: horizontal scroll of cards; HTML5 DnD or pointer-based reorder; ghost card while dragging.
- Drop zone per card for image replace (reuse `uploadScene`).
- Selected card → compact detail (existing scene controls: ambience, regenerate, upload).
- **Subtitles** row: toggle Burn, segmented Size, segmented Position.
- Overlay preview: caption sample text (first ~8 words of scene narration) positioned/scaled on the still.

### Copy

- Strip empty state: “Images land here — drag to reorder story beats.”
- Subtitles: “Burned into the final MP4 on Assemble.”

## Composer changes

- Read `edit_settings.json` (or request fields) when assembling.
- Pass `burn_captions`, size, position into `FFmpegComposer` / `render_caption_rgba` / overlay layout.
- Scene iteration order = script.scenes array order after reorder.

## Success criteria

- User can drag scene A before scene B; after assemble, visuals and VO follow the new order.
- Replacing an image on a card updates only that `scene_id`.
- Turning burn off produces an MP4 without burned captions (sidecar `.srt` may still be written when cues exist — optional; v1: skip burn overlays when off; still write `.srt` for download).
- Size/position visibly change burned captions vs default.
- Preview on still matches assemble placement within reasonable tolerance (same position constants).

## Risks / mitigations

| Risk | Mitigation |
|------|------------|
| Reorder breaks timing/ambience alignment | Remap timing segments as whole scene blocks; tests with 3-scene fixture |
| Large jobs (80 scenes) strip UX | Virtualize or paginate strip; DnD within loaded window |
| Caption preview ≠ final encode | Share position/size constants between preview CSS and Pillow layout |
| Completed jobs | Reopen / `can_edit` already allows reassemble after edits |

## Implementation phases

1. Backend: `edit_settings.json` + GET/PUT + workspace field  
2. Backend: scene reorder + timing remap + tests  
3. Composer: honor burn/size/position  
4. Frontend: Edit strip + DnD + subtitle controls + preview  
5. Wire Assemble to current settings; manual QA checklist  

## Follow-ups (not v1)

- Font / color / outline  
- Trim scene in/out  
- Undo stack for reorder  
- Realtime assemble progress with caption scrub  
