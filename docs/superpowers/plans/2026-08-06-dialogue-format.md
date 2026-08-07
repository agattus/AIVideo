# Dialogue Format + Create UX Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `format=dialogue` (3–4 cast, multi-voice lines, nameplates) and two all-format fixes: auto duration/max-scenes, and aspect-correct image generation for 9:16.

**Architecture:** Keep `style` as visual/BGM only. Extend `format` with `dialogue`. LLM returns `cast[]` / `lines[]` / `visual_beats[]`; pure expanders produce HITL scenes + line timing; TTS synthesizes each line with a cast voice and concatenates; FFmpeg burns captions + soft-fail nameplates. Separately, hide create-form duration/max-scenes (server derives budgets) and make Gemini (and save path) honor job aspect ratio.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, Edge-TTS, FFmpeg + Pillow, Gemini image API, React/Vite studio, pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-06-dialogue-format-design.md`
- Default `format=narrative` — existing jobs identical when format omitted
- Dialogue: 3–4 cast, ~8–16 lines, ~4–6 visual beats, target ~45–90s, default aspect 9:16
- Voices: auto-cast at generate; studio remap + regen only (no create-form casting)
- Soft-fail nameplates; assemble must still produce a video
- Duration / max_scenes: optional on API; omitted preferred; UI hides both for all formats
- 9:16 image assets must be portrait before compose (not landscape-only crop at mux time)
- No YouTube auto-post; no lip-sync

## File map

| File | Responsibility |
|------|----------------|
| `src/youtube_pipeline/assets/image_aspect.py` | Aspect prompt suffix + normalize/crop helpers |
| `src/youtube_pipeline/assets/gemini_image.py` | Pass aspect into generate + normalize output |
| `src/youtube_pipeline/assets/hitl_workspace.py` | Pass aspect into auto-fill / single generate |
| `src/youtube_pipeline/script_engine/prompts.py` | `resolve_auto_scene_budget(format, aspect, …)` |
| `src/youtube_pipeline/api/schemas.py` | Optional duration/max_scenes; `dialogue` format |
| `src/youtube_pipeline/api/tasks.py` | Auto budget when omitted; map dialogue |
| `frontend/src/components/GenerateForm.tsx` | Hide duration/max scenes; Dialogue option |
| `src/youtube_pipeline/models.py` | `VideoFormat.DIALOGUE`, speaker/cast fields |
| `src/youtube_pipeline/dialogue/casting.py` | Auto voice assign + remap helpers |
| `src/youtube_pipeline/dialogue/beats.py` | Expand lines/beats → scenes + line timeline |
| `src/youtube_pipeline/script_engine/dialogue_prompts.py` | Dialogue LLM prompts |
| `src/youtube_pipeline/script_engine/schema.py` | Dialogue JSON schema / validation |
| `src/youtube_pipeline/script_engine/generator.py` | Dialogue generate branch |
| `src/youtube_pipeline/audio/tts.py` | Multi-voice per-line synthesize |
| `src/youtube_pipeline/video/nameplate_overlays.py` | Pillow speaker nameplates |
| `src/youtube_pipeline/video/ffmpeg_composer.py` | Apply nameplates by line timing |
| `src/youtube_pipeline/orchestrator.py` | Persist cast.json / voice_map.json / lines timing |
| `src/youtube_pipeline/assets/hitl_workspace.py` | Workspace cast + voice remap endpoints support |
| `frontend/src/components/JobStudio.tsx` | Cast panel + remap + regen VO |
| `tests/test_image_aspect.py` | Crop/normalize + gemini prompt aspect |
| `tests/test_auto_scene_budget.py` | Duration/max scenes derivation |
| `tests/test_dialogue_*.py` | Beats, casting, generator, TTS, overlays, API, smoke |

---

### Task 1: Aspect-correct image helpers + Gemini provider

**Files:**
- Create: `src/youtube_pipeline/assets/image_aspect.py`
- Modify: `src/youtube_pipeline/assets/gemini_image.py`
- Modify: `src/youtube_pipeline/assets/base.py` (optional `aspect_ratio` on protocol via docstring / callers)
- Test: `tests/test_image_aspect.py`

**Interfaces:**
- Produces:
  - `aspect_prompt_clause(aspect_ratio: str) -> str`
  - `target_size(aspect_ratio: str, *, long_edge: int = 1280) -> tuple[int, int]`
  - `normalize_image_to_aspect(image_bytes: bytes, aspect_ratio: str) -> bytes` (PNG/JPEG out)
- `GeminiImageProvider.fetch_for_scene(scene, output_dir, *, aspect_ratio: str = "16:9")`

- [ ] **Step 1: Failing tests**

```python
# tests/test_image_aspect.py
from io import BytesIO
from PIL import Image
from youtube_pipeline.assets.image_aspect import (
    aspect_prompt_clause,
    normalize_image_to_aspect,
    target_size,
)

def test_target_size_vertical():
    w, h = target_size("9:16", long_edge=1280)
    assert h > w
    assert abs((h / w) - (16 / 9)) < 0.02

def test_normalize_crops_landscape_to_portrait():
    img = Image.new("RGB", (1600, 900), color=(20, 20, 20))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    out = normalize_image_to_aspect(buf.getvalue(), "9:16")
    result = Image.open(BytesIO(out))
    assert result.height > result.width
    assert abs((result.height / result.width) - (16 / 9)) < 0.05

def test_aspect_prompt_mentions_vertical():
    clause = aspect_prompt_clause("9:16")
    assert "9:16" in clause or "vertical" in clause.lower()
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/test_image_aspect.py -v`

- [ ] **Step 3: Implement**

`image_aspect.py`:
- Map `9:16` → portrait size; `16:9` → landscape; `1:1` → square
- `normalize_image_to_aspect`: open bytes, center-crop to target ratio, resize to `target_size`, return JPEG/PNG bytes
- `aspect_prompt_clause`: e.g. `"Frame: vertical 9:16 portrait, subject fully in frame, no letterboxing."`

`gemini_image.py`:
- `fetch_for_scene(..., *, aspect_ratio: str = "16:9")`
- Prompt = `f"{scene.visual_prompt}\n\n{aspect_prompt_clause(aspect_ratio)}"`
- After `_generate`, run `normalize_image_to_aspect` before write
- If Gemini SDK supports image aspect/size config for the configured model, set it; otherwise prompt + normalize is required minimum

- [ ] **Step 4: PASS + commit**

```bash
git add src/youtube_pipeline/assets/image_aspect.py src/youtube_pipeline/assets/gemini_image.py tests/test_image_aspect.py
git commit -m "fix: generate and normalize scene images to job aspect ratio"
```

---

### Task 2: Wire aspect into auto-fill and single-scene generate

**Files:**
- Modify: `src/youtube_pipeline/assets/hitl_workspace.py`
- Modify: `src/youtube_pipeline/assets/ai_generator.py` (if used; pass-through aspect)
- Modify: `src/youtube_pipeline/assets/provider.py` (stock path: still normalize saved bytes when possible)
- Test: `tests/test_image_aspect.py` (add auto-fill wiring test with mock provider)

**Interfaces:**
- Consumes: request/script `aspect_ratio` already loaded in workspace helpers
- `auto_fill_scene_images` / single-scene generate call `fetch_for_scene(..., aspect_ratio=...)`

- [ ] **Step 1: Failing test**

```python
def test_auto_fill_passes_aspect_to_provider(tmp_path, monkeypatch):
    # Arrange a mini run_dir with prompts.json aspect 9:16 and one missing scene
    # Monkeypatch build_asset_provider to a fake that records aspect_ratio kwarg
    # Call auto_fill_scene_images(run_dir)
    # Assert fake saw aspect_ratio == "9:16"
    ...
```

(Implement the fixture using existing `write_json` / prompts shape from other HITL tests.)

- [ ] **Step 2: Implement — read aspect from request.json / prompts payload; pass into `fetch_for_scene`**

Also normalize in `save_scene_image` path if provider ignored aspect (belt-and-suspenders: normalize bytes immediately before `save_scene_image` when aspect known).

- [ ] **Step 3: PASS + commit**

```bash
git add src/youtube_pipeline/assets/hitl_workspace.py tests/test_image_aspect.py
git commit -m "fix: pass job aspect ratio into scene image auto-fill"
```

---

### Task 3: Auto duration / max scenes (API + UI)

**Files:**
- Modify: `src/youtube_pipeline/script_engine/prompts.py` — add `resolve_auto_scene_budget`
- Modify: `src/youtube_pipeline/api/schemas.py` — `duration` / `max_scenes` Optional
- Modify: `src/youtube_pipeline/api/tasks.py` — apply auto budget
- Modify: `frontend/src/api/types.ts` — optional fields
- Modify: `frontend/src/components/GenerateForm.tsx` — remove duration/max scenes controls; omit from payload
- Rebuild: `frontend` → `web/`
- Test: `tests/test_auto_scene_budget.py`, `tests/test_quiz_api.py` (generate without duration still 202)

**Interfaces:**
- Produces: `resolve_auto_scene_budget(*, format: VideoFormat, aspect_ratio: AspectRatio, quiz_mode=None, question_count=None) -> tuple[int, int]` returning `(duration_seconds, max_scenes)`

- [ ] **Step 1: Failing tests**

```python
from youtube_pipeline.models import AspectRatio, QuizMode, VideoFormat
from youtube_pipeline.script_engine.prompts import resolve_auto_scene_budget

def test_dialogue_vertical_budget():
    dur, scenes = resolve_auto_scene_budget(
        format=VideoFormat.DIALOGUE, aspect_ratio=AspectRatio.VERTICAL
    )
    assert 45 <= dur <= 90
    assert 4 <= scenes <= 8

def test_quizverse_comment_budget():
    dur, scenes = resolve_auto_scene_budget(
        format=VideoFormat.QUIZVERSE,
        aspect_ratio=AspectRatio.VERTICAL,
        quiz_mode=QuizMode.COMMENT,
        question_count=1,
    )
    assert dur <= 60
    assert scenes >= 2

def test_narrative_landscape_budget():
    dur, scenes = resolve_auto_scene_budget(
        format=VideoFormat.NARRATIVE, aspect_ratio=AspectRatio.LANDSCAPE
    )
    assert dur >= 60
    assert scenes >= 6
```

Exact numbers may be tuned; keep ranges matching the asserts.

Suggested defaults to implement:
- Dialogue + any aspect: duration=75, max_scenes=6
- Quizverse comment: duration=30, max_scenes=max(4, 2 + 2*question_count)
- Quizverse reveal: duration=max(60, question_count * 20 + 10), max_scenes=max(4, question_count * 3 + 2)
- Narrative 9:16: duration=45, max_scenes=6
- Narrative 16:9 / 1:1: duration=90, max_scenes=10

- [ ] **Step 2: API — make `duration` and `max_scenes` optional (`None` default); in `tasks.py` if None, call `resolve_auto_scene_budget`**

If client still sends values, use them as soft overrides for narrative only; quizverse structure still driven by `question_count`; dialogue prefers auto (ignore client duration/max_scenes or clamp into 45–90 / 4–8).

- [ ] **Step 3: Frontend — remove Duration and Max scenes fields; stop sending them in `generateVideo` payload**

- [ ] **Step 4: `npm run build` + tests PASS + commit**

```bash
cd frontend && npm run build
git add src/youtube_pipeline/script_engine/prompts.py src/youtube_pipeline/api frontend/src web tests/test_auto_scene_budget.py
git commit -m "feat: auto-select duration and max scenes from format and aspect"
```

---

### Task 4: Dialogue models

**Files:**
- Modify: `src/youtube_pipeline/models.py`
- Test: `tests/test_dialogue_models.py`

**Interfaces:**
- `VideoFormat.DIALOGUE = "dialogue"`
- `SceneData.speaker_id: str | None = None`
- `SceneData.speaker_name: str = ""`
- `SceneData.line_start: int | None = None`
- `SceneData.line_end: int | None = None`
- Optional `BeatType.DIALOGUE_LINE` not required if visual beats use `NARRATION` + speaker metadata

- [ ] **Step 1: Failing test — `PipelineRequest(format=VideoFormat.DIALOGUE, …)` validates; SceneData accepts speaker fields**

- [ ] **Step 2: Implement enums/fields**

- [ ] **Step 3: PASS + commit**

```bash
git add src/youtube_pipeline/models.py tests/test_dialogue_models.py
git commit -m "feat: add dialogue format and speaker fields on scenes"
```

---

### Task 5: Casting + beat expander (pure)

**Files:**
- Create: `src/youtube_pipeline/dialogue/__init__.py`
- Create: `src/youtube_pipeline/dialogue/casting.py`
- Create: `src/youtube_pipeline/dialogue/beats.py`
- Test: `tests/test_dialogue_beats.py`, `tests/test_dialogue_casting.py`

**Interfaces:**
- `assign_voices(cast: list[dict], *, language: str = "en") -> dict[str, str]`  # cast_id → edge voice id
- `expand_dialogue_script(*, cast, lines, visual_beats, language="en") -> tuple[list[SceneData], list[dict]]`
  - Returns (visual beat scenes for HITL, normalized lines with speaker_name)
- Validate: cast length 3–4; every line.speaker_id in cast; beats cover all line indices without gaps/overlaps

- [ ] **Step 1: Failing tests for expand + voice assign uniqueness (3–4 distinct voices when locale allows)**

```python
def test_expand_dialogue_builds_visual_scenes():
    cast = [
        {"id": "a", "name": "Ravi", "gender_hint": "male"},
        {"id": "b", "name": "Maya", "gender_hint": "female"},
        {"id": "c", "name": "Old Guard", "gender_hint": "male"},
    ]
    lines = [
        {"speaker_id": "a", "text": "We leave at dawn."},
        {"speaker_id": "b", "text": "The gate won't open."},
        {"speaker_id": "c", "text": "Then we climb."},
    ]
    beats = [{"visual_prompt": "Moonlit fort gate", "line_start": 0, "line_end": 2}]
    scenes, norm_lines = expand_dialogue_script(cast=cast, lines=lines, visual_beats=beats)
    assert len(scenes) == 1
    assert scenes[0].line_start == 0 and scenes[0].line_end == 2
    assert norm_lines[0]["speaker_name"] == "Ravi"
```

- [ ] **Step 2: Implement casting heuristics** — pick from Edge locale voices by gender_hint; fall back to language default voices list; never assign the same voice to two cast members when ≥N voices exist

- [ ] **Step 3: PASS + commit**

```bash
git add src/youtube_pipeline/dialogue tests/test_dialogue_beats.py tests/test_dialogue_casting.py
git commit -m "feat: expand dialogue cast, lines, and visual beats"
```

---

### Task 6: Dialogue prompts + generator branch

**Files:**
- Create: `src/youtube_pipeline/script_engine/dialogue_prompts.py`
- Modify: `src/youtube_pipeline/script_engine/schema.py` — `DIALOGUE_SCRIPT_SCHEMA` + `validate_dialogue_script_payload`
- Modify: `src/youtube_pipeline/script_engine/generator.py`
- Test: `tests/test_dialogue_generator.py`

**Interfaces:**
- `ScriptEngine.generate` branches on `VideoFormat.DIALOGUE`
- Persist on returned script: `format="dialogue"`; scenes = visual beats; stash `cast`, `lines`, `voice_map` on script extras or parallel attributes consumed by orchestrator (prefer `VideoScript` optional fields or `model_config` extras already used for quiz — mirror quiz `questions` pattern: attach `cast`/`lines`/`voice_map` attributes on engine result object or return tuple; simplest: set attributes on `VideoScript` via optional fields)

Add to `VideoScript` if needed:
```python
cast: list[dict] = Field(default_factory=list)
lines: list[dict] = Field(default_factory=list)
voice_map: dict[str, str] = Field(default_factory=dict)
```

- [ ] **Step 1: Failing mocked LLM test → expands beats, assigns voices, format dialogue**

- [ ] **Step 2: Implement prompts requiring 3–4 cast, 8–16 lines, 4–6 beats, language-correct dialogue**

- [ ] **Step 3: Validation + 3-attempt corrective retry (same pattern as quizverse)**

- [ ] **Step 4: PASS + commit**

```bash
git add src/youtube_pipeline/script_engine tests/test_dialogue_generator.py src/youtube_pipeline/models.py
git commit -m "feat: generate dialogue scripts with cast and visual beats"
```

---

### Task 7: Multi-voice TTS for dialogue

**Files:**
- Modify: `src/youtube_pipeline/audio/tts.py`
- Test: `tests/test_dialogue_tts.py`

**Interfaces:**
- When `script.format == "dialogue"` and `script.lines` non-empty:
  - For each line, Edge-TTS with `voice_map[speaker_id]`
  - Insert ~300ms silence between lines
  - Build timing list: `{speaker_id, speaker_name, text, start, end}`
  - Write timing to return value / `timing["lines"]`
- Visual scene durations = sum of line durations for lines in `[line_start, line_end]`
- Inter-scene pause 0 for dialogue (line gaps already present)
- Narrative/quizverse paths unchanged

- [ ] **Step 1: Failing test with mocked `_synthesize_edge_tts` / silence / probe**

- [ ] **Step 2: Implement `_synthesize_dialogue_lines(...)`**

- [ ] **Step 3: PASS + commit**

```bash
git add src/youtube_pipeline/audio/tts.py tests/test_dialogue_tts.py
git commit -m "feat: synthesize dialogue lines with per-character voices"
```

---

### Task 8: Nameplate overlays + composer

**Files:**
- Create: `src/youtube_pipeline/video/nameplate_overlays.py`
- Modify: `src/youtube_pipeline/video/ffmpeg_composer.py`
- Test: `tests/test_nameplate_overlays.py`

**Interfaces:**
- `render_nameplate_png(name: str, *, dest: Path, width: int, height: int, language: str = "en") -> Path`
- Composer, when `script.format == "dialogue"` and line timings present: overlay nameplates with `enable='between(t,start,end)'` (soft-fail)

- [ ] **Step 1: Failing PNG existence test + composer enable-window test (mock ffmpeg like quiz overlays)**

- [ ] **Step 2: Implement small top/lower-third nameplate (not full-card quiz style)**

- [ ] **Step 3: PASS + commit**

```bash
git add src/youtube_pipeline/video/nameplate_overlays.py src/youtube_pipeline/video/ffmpeg_composer.py tests/test_nameplate_overlays.py
git commit -m "feat: burn dialogue speaker nameplates during compose"
```

---

### Task 9: API + orchestrator + workspace cast

**Files:**
- Modify: `src/youtube_pipeline/api/schemas.py` — workspace cast fields; generate accepts `dialogue`
- Modify: `src/youtube_pipeline/api/tasks.py`
- Modify: `src/youtube_pipeline/orchestrator.py` — write `cast.json`, `voice_map.json`, `dialogue_lines.json`
- Modify: `src/youtube_pipeline/assets/hitl_workspace.py` — expose cast in workspace
- Modify: `src/youtube_pipeline/api/main.py` — endpoint `POST /jobs/{id}/cast/voices` to update voice_map + optional regen flag wiring
- Test: `tests/test_dialogue_api.py`

**Interfaces:**
- Workspace includes `cast: [{id, name, voice_id}]`
- Voice update persists `voice_map.json` and can trigger existing voiceover regen path with dialogue-aware TTS

- [ ] **Step 1: API schema test accepts format=dialogue without duration**

- [ ] **Step 2: Persist sidecars after Phase 1; workspace lists cast**

- [ ] **Step 3: PASS + commit**

```bash
git add src/youtube_pipeline/api src/youtube_pipeline/orchestrator.py src/youtube_pipeline/assets/hitl_workspace.py tests/test_dialogue_api.py
git commit -m "feat: expose dialogue cast on API and studio workspace"
```

---

### Task 10: Frontend Dialogue + cast panel

**Files:**
- Modify: `frontend/src/api/types.ts`, `client.ts`
- Modify: `frontend/src/components/GenerateForm.tsx` — Format option Dialogue; default aspect 9:16 on select
- Modify: `frontend/src/components/JobStudio.tsx` — Cast collapsible: voice select per character, preview, save/remap, regen VO
- Rebuild: `web/`

- [ ] **Step 1: Types + generate payload `format: "dialogue"`**

- [ ] **Step 2: GenerateForm Dialogue branch (aspect default 9:16)**

- [ ] **Step 3: JobStudio Cast UI when `workspace.format === "dialogue"`**

- [ ] **Step 4: `npm run build` + commit**

```bash
cd frontend && npm run build
git add frontend/src web
git commit -m "feat: Dialogue format in create form and studio cast panel"
```

---

### Task 11: E2E smoke + regression

**Files:**
- Test: `tests/test_dialogue_e2e_smoke.py`

- [ ] **Step 1: Smoke — mocked LLM dialogue → scenes/beats/voice_map; caption inputs include speaker lines; narrative generate without duration still works**

- [ ] **Step 2: Run slice**

```bash
pytest tests/test_image_aspect.py tests/test_auto_scene_budget.py tests/test_dialogue_models.py tests/test_dialogue_beats.py tests/test_dialogue_casting.py tests/test_dialogue_generator.py tests/test_dialogue_tts.py tests/test_nameplate_overlays.py tests/test_dialogue_api.py tests/test_dialogue_e2e_smoke.py tests/test_quiz_api.py tests/test_quiz_e2e_smoke.py -q
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_dialogue_e2e_smoke.py
git commit -m "test: dialogue smoke and create-UX regression slice"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Aspect-correct image gen | 1, 2 |
| Auto duration / max scenes | 3 |
| `format=dialogue` models | 4 |
| Cast 3–4 + expand beats | 5 |
| LLM dialogue generate | 6 |
| Multi-voice TTS | 7 |
| Nameplates | 8 |
| Studio cast remap | 9, 10 |
| Create form Dialogue | 10 |
| Narrative default / regression | 3, 11 |
| Soft-fail overlays | 8 |

## Placeholder scan

None intentional. Gemini native aspect config is best-effort; prompt + `normalize_image_to_aspect` is the merge-blocking requirement.
