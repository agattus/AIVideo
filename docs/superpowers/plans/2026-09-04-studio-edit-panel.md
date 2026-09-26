# Studio Edit Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a JobStudio **Edit** panel with drag-reorder scene strip and subtitle settings (burn / size / position) that persist on the job and apply on Assemble.

**Architecture:** Stable `scene_id` keeps asset filenames; reorder rewrites script/timing array order. Subtitle prefs live in `edit_settings.json` under the run dir, exposed on workspace, and read by `FFmpegComposer` at assemble.

**Tech Stack:** FastAPI, existing HITL workspace helpers, FFmpegComposer + Pillow captions, React JobStudio (HTML5 DnD), Vite frontend

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-04-studio-edit-panel-design.md`
- Reorder moves **whole scene** (image + narration + timing), not picture-only
- No full NLE, no font/color pickers in v1
- Auth: reuse `require_user` / `user_owns_job` on new routes
- UI: existing S-Studio tokens (Syne / DM Sans); no purple-on-white or cream-terracotta cliché
- Worktree: `.worktrees/dialogue-format`

---

### File map

| File | Responsibility |
|------|----------------|
| `src/youtube_pipeline/assets/edit_settings.py` | Load/save `edit_settings.json`; defaults |
| `src/youtube_pipeline/assets/scene_reorder.py` | Permute script + timing by `scene_ids` |
| `src/youtube_pipeline/api/schemas.py` | `EditSettings`, reorder request, workspace field |
| `src/youtube_pipeline/api/main.py` | GET/PUT edit-settings, POST scenes/reorder |
| `src/youtube_pipeline/assets/hitl_workspace.py` | Include edit_settings in workspace payload |
| `src/youtube_pipeline/video/text_clips.py` | Caption vertical position + size scale |
| `src/youtube_pipeline/video/ffmpeg_composer.py` | Honor burn/size/position |
| `src/youtube_pipeline/orchestrator.py` | Load edit_settings when configuring composer |
| `frontend/src/api/types.ts` + `client.ts` | Types + API helpers |
| `frontend/src/components/EditPanel.tsx` | Scene strip DnD + subtitle controls + preview |
| `frontend/src/components/JobStudio.tsx` | Mount Edit section |
| `frontend/src/styles/global.css` | Strip / preview styles |
| `tests/test_edit_settings.py` | Settings + API |
| `tests/test_scene_reorder.py` | Reorder + timing remap |
| `tests/test_caption_layout.py` | Size/position helpers |

---

### Task 1: Edit settings model + persistence

**Files:**
- Create: `src/youtube_pipeline/assets/edit_settings.py`
- Modify: `src/youtube_pipeline/api/schemas.py` (add `EditSettingsModel`)
- Test: `tests/test_edit_settings.py`

**Interfaces:**
- Produces: `DEFAULT_EDIT_SETTINGS`, `load_edit_settings(run_dir: Path) -> dict`, `save_edit_settings(run_dir: Path, data: dict) -> dict`
- Settings keys: `burn_captions: bool`, `caption_size: "s"|"m"|"l"`, `caption_position: "bottom"|"lower_third"`

- [ ] **Step 1: Write failing tests**

```python
from pathlib import Path
from youtube_pipeline.assets.edit_settings import load_edit_settings, save_edit_settings

def test_load_defaults_when_missing(tmp_path: Path) -> None:
    data = load_edit_settings(tmp_path)
    assert data["burn_captions"] is True
    assert data["caption_size"] == "m"
    assert data["caption_position"] == "bottom"

def test_save_roundtrip(tmp_path: Path) -> None:
    saved = save_edit_settings(
        tmp_path,
        {"burn_captions": False, "caption_size": "l", "caption_position": "lower_third"},
    )
    assert saved["burn_captions"] is False
    assert load_edit_settings(tmp_path)["caption_size"] == "l"

def test_rejects_invalid_size(tmp_path: Path) -> None:
    import pytest
    with pytest.raises(ValueError):
        save_edit_settings(tmp_path, {"caption_size": "xl"})
```

- [ ] **Step 2: Run tests — expect FAIL (module missing)**

Run: `pytest tests/test_edit_settings.py -q`

- [ ] **Step 3: Implement `edit_settings.py`**

```python
"""Persist Studio Edit panel options beside a job run directory."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from youtube_pipeline.utils.files import read_json, write_json

DEFAULT_EDIT_SETTINGS: dict[str, Any] = {
    "burn_captions": True,
    "caption_size": "m",
    "caption_position": "bottom",
}
_ALLOWED_SIZES = {"s", "m", "l"}
_ALLOWED_POSITIONS = {"bottom", "lower_third"}

def _normalize(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(DEFAULT_EDIT_SETTINGS)
    if not isinstance(raw, dict):
        return data
    if "burn_captions" in raw:
        data["burn_captions"] = bool(raw["burn_captions"])
    size = str(raw.get("caption_size") or data["caption_size"]).lower()
    if size not in _ALLOWED_SIZES:
        raise ValueError(f"caption_size must be one of {sorted(_ALLOWED_SIZES)}")
    data["caption_size"] = size
    pos = str(raw.get("caption_position") or data["caption_position"]).lower()
    if pos not in _ALLOWED_POSITIONS:
        raise ValueError(f"caption_position must be one of {sorted(_ALLOWED_POSITIONS)}")
    data["caption_position"] = pos
    return data

def load_edit_settings(run_dir: Path) -> dict[str, Any]:
    path = Path(run_dir) / "edit_settings.json"
    if not path.exists():
        return dict(DEFAULT_EDIT_SETTINGS)
    try:
        return _normalize(read_json(path))
    except Exception:
        return dict(DEFAULT_EDIT_SETTINGS)

def save_edit_settings(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    current = load_edit_settings(run_dir)
    merged = {**current, **(payload or {})}
    normalized = _normalize(merged)
    write_json(Path(run_dir) / "edit_settings.json", normalized)
    return normalized
```

Add Pydantic model in `schemas.py`:

```python
class EditSettingsModel(BaseModel):
    burn_captions: bool = True
    caption_size: Literal["s", "m", "l"] = "m"
    caption_position: Literal["bottom", "lower_third"] = "bottom"
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/test_edit_settings.py -q`

- [ ] **Step 5: Commit** (only if user asked for commits in-session; otherwise leave staged work uncommitted until asked)

---

### Task 2: Scene reorder helper

**Files:**
- Create: `src/youtube_pipeline/assets/scene_reorder.py`
- Test: `tests/test_scene_reorder.py`

**Interfaces:**
- Consumes: `script.json` / `script_timed.json` / `timing.json` shapes already used by HITL
- Produces: `reorder_scenes(run_dir: Path, scene_ids: list[int]) -> dict`  
  Returns `{ "scene_ids": [...], "scene_count": N }`  
  Raises `ValueError` if permutation incomplete / unknown ids

- [ ] **Step 1: Write failing test with a tiny fixture**

```python
import json
from pathlib import Path
from youtube_pipeline.assets.scene_reorder import reorder_scenes

def _write_fixture(run: Path) -> None:
    script = {
        "title": "t",
        "full_script": "A. B. C.",
        "style": "cinematic",
        "scenes": [
            {"scene_id": 0, "script_text": "A.", "visual_prompt": "va", "duration": 1.5},
            {"scene_id": 1, "script_text": "B.", "visual_prompt": "vb", "duration": 2.0},
            {"scene_id": 2, "script_text": "C.", "visual_prompt": "vc", "duration": 1.0},
        ],
    }
    timing = {
        "total_duration": 4.5,
        "scenes": [
            {"scene_id": 0, "start": 0.0, "end": 1.5, "duration": 1.5, "speech_duration": 1.5, "pause_after": 0.0},
            {"scene_id": 1, "start": 1.5, "end": 3.5, "duration": 2.0, "speech_duration": 2.0, "pause_after": 0.0},
            {"scene_id": 2, "start": 3.5, "end": 4.5, "duration": 1.0, "speech_duration": 1.0, "pause_after": 0.0},
        ],
        "words": [],
    }
    (run / "script.json").write_text(json.dumps(script), encoding="utf-8")
    (run / "script_timed.json").write_text(json.dumps(script), encoding="utf-8")
    (run / "timing.json").write_text(json.dumps(timing), encoding="utf-8")

def test_reorder_permutes_script_and_retimes(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    reorder_scenes(tmp_path, [2, 0, 1])
    script = json.loads((tmp_path / "script.json").read_text(encoding="utf-8"))
    assert [s["scene_id"] for s in script["scenes"]] == [2, 0, 1]
    timing = json.loads((tmp_path / "timing.json").read_text(encoding="utf-8"))
    assert [s["scene_id"] for s in timing["scenes"]] == [2, 0, 1]
    assert timing["scenes"][0]["start"] == 0.0
    assert timing["scenes"][0]["duration"] == 1.0
    assert timing["scenes"][1]["start"] == 1.0
    assert abs(timing["total_duration"] - 4.5) < 0.01

def test_reorder_rejects_bad_permutation(tmp_path: Path) -> None:
    import pytest
    _write_fixture(tmp_path)
    with pytest.raises(ValueError):
        reorder_scenes(tmp_path, [0, 1])
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/test_scene_reorder.py -q`

- [ ] **Step 3: Implement reorder**

Algorithm:
1. Load script from `script_timed.json` if present else `script.json`
2. Build `by_id = {scene_id: scene}`
3. Validate `scene_ids` is a permutation of existing ids
4. New scenes list = `[by_id[i] for i in scene_ids]`
5. Rewrite `full_script` as `" ".join(s.script_text for s in new_scenes)`
6. For timing: reorder timing scene blocks by id; recompute `start`/`end` as cumulative sum of each block’s `duration` (prefer existing `duration`; fallback `speech_duration + pause_after`)
7. Write `script.json`, `script_timed.json`, `timing.json`
8. Do **not** rename `assets/scene_XX.jpg`

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/test_scene_reorder.py -q`

---

### Task 3: API routes + workspace field

**Files:**
- Modify: `src/youtube_pipeline/api/schemas.py` — add `EditSettingsModel`, `SceneReorderRequest`, field on `WorkspaceResponse`
- Modify: `src/youtube_pipeline/assets/hitl_workspace.py` — include `edit_settings` in `workspace_status`
- Modify: `src/youtube_pipeline/api/main.py` — routes + wire `_workspace_response`
- Test: extend `tests/test_edit_settings.py` with TestClient cases (or `tests/test_edit_api.py`)

**Interfaces:**
- `GET /api/v1/jobs/{job_id}/edit-settings` → `EditSettingsModel`
- `PUT /api/v1/jobs/{job_id}/edit-settings` body `EditSettingsModel` → saved model
- `POST /api/v1/jobs/{job_id}/scenes/reorder` body `{ "scene_ids": int[] }` → `{ job_id, scene_ids, message }`
- `WorkspaceResponse.edit_settings: EditSettingsModel`

- [ ] **Step 1: Write API tests** using existing TestClient + fake redis pattern from `tests/test_api.py` (init job with run_dir fixture containing script/timing)

- [ ] **Step 2: Run — expect FAIL (404 routes)**

- [ ] **Step 3: Implement routes** with `user: AuthUser = Depends(require_user)` and `_require_job_run_dir(..., user=user)`

- [ ] **Step 4: Run API tests — PASS**

---

### Task 4: Composer caption layout

**Files:**
- Modify: `src/youtube_pipeline/video/text_clips.py` — `render_caption_rgba(..., size_scale=1.0, position="bottom")` or separate layout helper
- Modify: `src/youtube_pipeline/video/ffmpeg_composer.py` — store `caption_size`, `caption_position`; scale `_caption_font_size`; place overlays
- Modify: `src/youtube_pipeline/orchestrator.py` `_configure_composer` — load `edit_settings` from run_dir and set composer flags (`burn_captions` already exists on request; prefer run_dir settings when present)
- Test: `tests/test_caption_layout.py`

**Interfaces:**
- Size scale map: `s=0.82`, `m=1.0`, `l=1.22`
- Position: `bottom` ≈ current padding from bottom; `lower_third` ≈ higher (e.g. 28% from bottom of frame)

- [ ] **Step 1: Unit test scale + position offsets** (pure functions; no ffmpeg)

```python
from youtube_pipeline.video.text_clips import caption_size_scale, caption_bottom_padding_ratio

def test_caption_size_scales() -> None:
    assert caption_size_scale("s") == 0.82
    assert caption_size_scale("m") == 1.0
    assert caption_size_scale("l") == 1.22

def test_caption_position_ratios() -> None:
    assert caption_bottom_padding_ratio("bottom") < caption_bottom_padding_ratio("lower_third")
```

- [ ] **Step 2: Implement helpers + wire composer**

When `burn_captions` is False, skip caption overlay loop (still allow writing sidecar SRT from cues if already built — spec: write `.srt` for download even when burn off).

- [ ] **Step 3: Run `pytest tests/test_caption_layout.py -q` — PASS**

---

### Task 5: Frontend types + API client

**Files:**
- Modify: `frontend/src/api/types.ts` — `EditSettings`, add to `WorkspaceResponse`
- Modify: `frontend/src/api/client.ts` — `getEditSettings`, `putEditSettings`, `reorderScenes`

```typescript
export type CaptionSize = "s" | "m" | "l";
export type CaptionPosition = "bottom" | "lower_third";
export interface EditSettings {
  burn_captions: boolean;
  caption_size: CaptionSize;
  caption_position: CaptionPosition;
}
```

- [ ] **Step 1: Add types + client helpers using `apiFetch` / `authHeaders`**
- [ ] **Step 2: `npm run build` in `frontend/` — PASS** (or `tsc -b`)

---

### Task 6: EditPanel UI

**Files:**
- Create: `frontend/src/components/EditPanel.tsx`
- Modify: `frontend/src/components/JobStudio.tsx` — new section `edit` in accordion
- Modify: `frontend/src/styles/global.css` — `.edit-strip`, `.edit-card`, `.caption-preview`

**Behavior:**
- Props: `jobId`, `scenes`, `canEdit`, `editSettings`, `onChanged` (refresh workspace)
- Strip: map scenes in current order; `draggable`; on drop call `reorderScenes` with full id list
- Card: thumb from `preview_url`, badge scene number; file input / drop → `uploadScene`
- Subtitles: checkbox burn; buttons S/M/L; bottom / lower-third; optimistic local state then `putEditSettings`
- Preview: absolutely positioned sample text on selected thumb using same size/position classes

- [ ] **Step 1: Implement `EditPanel`**
- [ ] **Step 2: Mount in JobStudio** between Quality and Assemble (or above Assemble)
- [ ] **Step 3: Build frontend — PASS**
- [ ] **Step 4: Manual check** at http://127.0.0.1:5173/studio/:jobId — reorder, toggle captions, assemble

---

### Task 7: Verification checklist

- [ ] `pytest tests/test_edit_settings.py tests/test_scene_reorder.py tests/test_caption_layout.py tests/test_edit_api.py -q`
- [ ] Reorder 3-scene job → assemble → VO/images follow new order
- [ ] `burn_captions: false` → no burned text on MP4; `.srt` still downloadable if present
- [ ] Size L + lower_third visibly different from default

---

## Spec coverage

| Spec item | Task |
|-----------|------|
| edit_settings.json | 1 |
| Scene reorder whole-scene | 2–3 |
| API + workspace field | 3 |
| Composer burn/size/position | 4 |
| Edit strip + subtitle UI | 5–6 |
| Success criteria / QA | 7 |

## Placeholder scan

None intentional — commit steps are gated on user request per repo commit rules.
