# Shot-Synced Stills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make films feel shot-by-shot with free stills: Dialogue gets one image per line synced to VO; creators pick duration; max scenes stay auto; denser Narrative/Quizverse budgets; snappier Ken Burns fades.

**Architecture:** Keep still images + FFmpeg Ken Burns (no AI video). Change Dialogue expand so each line becomes its own `SceneData` with a distinct visual prompt. Prefer creator `duration` in `resolve_auto_scene_budget` / `_build_pipeline_request`, while `max_scenes` remains server-derived. Restore duration on the create form only. Tune compose edge fades for short-form / dialogue.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, Edge-TTS, FFmpeg, React/Vite studio, pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-06-shot-synced-stills-design.md`
- No Veo/Kling/Runway or any paid AI video API in this plan
- Duration: creator-selected on create; API may omit (keep defaults)
- Max scenes: never shown in UI; always auto (Dialogue final count = `len(lines)`)
- Dialogue cast / multi-voice TTS / nameplates unchanged
- Soft-fail per-scene image errors when a retry path exists; do not require perfect Gemini free quota
- Branch / worktree: continue on `feat/dialogue-format` unless a fresh branch is requested

## File map

| File | Responsibility |
|------|----------------|
| `src/youtube_pipeline/dialogue/beats.py` | Expand to one scene per dialogue line |
| `src/youtube_pipeline/script_engine/dialogue_prompts.py` | Ask for per-line (or 1:1) visual prompts |
| `src/youtube_pipeline/script_engine/schema.py` | Accept optional `visual_prompt` on lines; keep beats optional/soft |
| `src/youtube_pipeline/script_engine/generator.py` | Wire expander; no multi-line scene collapse |
| `src/youtube_pipeline/script_engine/prompts.py` | Duration-aware denser `resolve_auto_scene_budget` |
| `src/youtube_pipeline/api/tasks.py` | Honor creator duration for all formats; auto max_scenes |
| `src/youtube_pipeline/api/schemas.py` | Duration optional with clear description |
| `frontend/src/components/GenerateForm.tsx` | Restore duration control; omit max_scenes |
| `frontend/src/api/types.ts` | Ensure `duration` on generate payload |
| `src/youtube_pipeline/video/ffmpeg_composer.py` | Snappier fades for dialogue / 9:16 |
| `tests/test_dialogue_beats.py` | Per-line scene expansion |
| `tests/test_auto_scene_budget.py` | Duration-scaled budgets |
| `tests/test_shot_synced_compose.py` | Ken Burns fade / pattern variation |
| `tests/test_dialogue_e2e_smoke.py` | N lines → N scenes regression |

---

### Task 1: Dialogue expander — one scene per line

**Files:**
- Modify: `src/youtube_pipeline/dialogue/beats.py`
- Test: `tests/test_dialogue_beats.py`

**Interfaces:**
- Consumes: `cast`, `lines`, optional `visual_beats`
- Produces: `expand_dialogue_script(...) -> (list[SceneData], list[dict])` where `len(scenes) == len(lines)` and each scene has `line_start == line_end == i`

- [ ] **Step 1: Write the failing test**

```python
def test_expand_dialogue_one_scene_per_line() -> None:
    beats = [
        {"visual_prompt": "Moonlit fort gate", "line_start": 0, "line_end": 1},
        {"visual_prompt": "Climbing the wall", "line_start": 2, "line_end": 2},
    ]
    scenes, normalized = expand_dialogue_script(
        cast=CAST, lines=LINES, visual_beats=beats
    )
    assert len(scenes) == len(LINES) == 3
    assert [(s.line_start, s.line_end) for s in scenes] == [(0, 0), (1, 1), (2, 2)]
    assert scenes[0].speaker_name == "Ravi"
    assert scenes[1].speaker_name == "Maya"
    assert "Moonlit" in scenes[0].visual_prompt
    assert scenes[0].visual_prompt != scenes[1].visual_prompt or "Maya" in scenes[1].visual_prompt
    assert scenes[0].script_text == "We leave at dawn."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dialogue_beats.py::test_expand_dialogue_one_scene_per_line -v`  
Expected: FAIL (currently one scene covers lines 0–1)

- [ ] **Step 3: Implement per-line expansion**

In `expand_dialogue_script`:
1. Normalize lines as today.
2. If `visual_beats` provided, validate coverage (keep existing validator) OR treat missing/empty beats as “synthesize later.”
3. For each line index `i`:
   - `base_prompt` = covering beat’s `visual_prompt` if any, else `f"Cinematic shot: {line['text']}"`
   - If line dict has non-empty `visual_prompt`, use that as `base_prompt`
   - Enrich when reusing a multi-line beat prompt:  
     `visual = f"{base_prompt}. Focus on {speaker_name}: {text}"`  
     (skip enrichment when line already had its own `visual_prompt`)
   - Emit `SceneData(scene_id=i, script_text=text, visual_prompt=visual, speaker_id=..., speaker_name=..., line_start=i, line_end=i)`

Update `test_expand_dialogue_builds_visual_scenes_and_normalizes_speakers` to expect 3 scenes.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_dialogue_beats.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/youtube_pipeline/dialogue/beats.py tests/test_dialogue_beats.py
git commit -m "feat: expand dialogue to one visual scene per line"
```

---

### Task 2: Dialogue prompts + schema for per-line visuals

**Files:**
- Modify: `src/youtube_pipeline/script_engine/dialogue_prompts.py`
- Modify: `src/youtube_pipeline/script_engine/schema.py`
- Test: `tests/test_dialogue_generator.py`

**Interfaces:**
- Consumes: Task 1 expander
- Produces: LLM instructions that prefer one visual per line; validation still accepts legacy multi-line beats (expander splits)

- [ ] **Step 1: Failing / updated generator expectation**

In `tests/test_dialogue_generator.py`, assert mocked LLM output with multi-line beats expands to `len(scenes) == len(lines)`.

- [ ] **Step 2: Update prompts**

Instruct the model to return either:
- `lines: [{speaker_id, text, visual_prompt}]` with a unique cinematic `visual_prompt` per line, **or**
- `visual_beats` with exactly one beat per line (`line_start == line_end`)

State that multi-line beats are discouraged; pipeline will split them.

- [ ] **Step 3: Schema**

Allow optional `visual_prompt` string on each line. Keep `visual_beats` optional-or-present; if present, coverage rules remain. Do not require beats length == lines (expander handles split).

- [ ] **Step 4: PASS + commit**

```bash
pytest tests/test_dialogue_generator.py tests/test_dialogue_beats.py -q
git add src/youtube_pipeline/script_engine/dialogue_prompts.py src/youtube_pipeline/script_engine/schema.py tests/test_dialogue_generator.py
git commit -m "feat: prefer per-line visual prompts in dialogue scripts"
```

---

### Task 3: Duration-aware auto max_scenes

**Files:**
- Modify: `src/youtube_pipeline/script_engine/prompts.py` (`resolve_auto_scene_budget`)
- Modify: `src/youtube_pipeline/api/tasks.py` (`_build_pipeline_request`)
- Test: `tests/test_auto_scene_budget.py`
- Test: `tests/test_dialogue_api.py` (duration honored)

**Interfaces:**
- Produces:  
  `resolve_auto_scene_budget(*, format, aspect_ratio, quiz_mode=None, question_count=None, duration_seconds: int | None = None) -> tuple[int, int]`  
  Returns `(duration, max_scenes)`. When `duration_seconds` is set, returned duration equals that value (clamped 15–3600). `max_scenes` is always computed (never taken from client for UI path).

- [ ] **Step 1: Failing tests**

```python
def test_narrative_max_scenes_scales_with_duration():
    _, short = resolve_auto_scene_budget(
        format=VideoFormat.NARRATIVE,
        aspect_ratio=AspectRatio.VERTICAL,
        duration_seconds=45,
    )
    _, long = resolve_auto_scene_budget(
        format=VideoFormat.NARRATIVE,
        aspect_ratio=AspectRatio.VERTICAL,
        duration_seconds=120,
    )
    assert long > short
    assert short >= 6

def test_dialogue_budget_uses_creator_duration_and_line_band():
    dur, scenes = resolve_auto_scene_budget(
        format=VideoFormat.DIALOGUE,
        aspect_ratio=AspectRatio.VERTICAL,
        duration_seconds=90,
    )
    assert dur == 90
    assert scenes >= 8  # room for ~8–16 lines
```

- [ ] **Step 2: Implement budget rules**

Suggested defaults (clamp scenes to `[2, 240]`):

| Format | Duration (if omitted) | max_scenes |
|--------|----------------------|------------|
| Dialogue | 75 | `max(8, min(16, round(duration/6)))` |
| Quiz Comment | 30 (or creator) | keep `max(4, 2+2*count)`; if duration>45 add `+ duration//30` B-roll headroom |
| Quiz Reveal | `max(60, count*20+10)` or creator | keep `max(4, count*3+2)`; if creator duration longer, `+ (duration-base)//20` |
| Narrative 9:16 | 45 or creator | `max(6, min(24, round(duration/8)))` |
| Narrative 16:9/1:1 | 90 or creator | `max(8, min(40, round(duration/9)))` |

- [ ] **Step 3: Wire tasks**

In `_build_pipeline_request`:
```python
raw_duration = request_data.get("duration")
requested = int(raw_duration) if raw_duration is not None else None
duration, max_scenes = resolve_auto_scene_budget(
    format=video_format,
    aspect_ratio=aspect_ratio,
    quiz_mode=quiz_mode,
    question_count=question_count,
    duration_seconds=requested,
)
# Do not apply client max_scenes from UI. Optional: allow API override only if explicitly present AND format==NARRATIVE for back-compat — prefer ignoring client max_scenes entirely per spec.
```

- [ ] **Step 4: PASS + commit**

```bash
pytest tests/test_auto_scene_budget.py tests/test_dialogue_api.py -q
git add src/youtube_pipeline/script_engine/prompts.py src/youtube_pipeline/api/tasks.py tests/test_auto_scene_budget.py tests/test_dialogue_api.py
git commit -m "feat: honor creator duration and denser auto max scenes"
```

---

### Task 4: Create form — restore duration

**Files:**
- Modify: `frontend/src/components/GenerateForm.tsx`
- Modify: `frontend/src/api/types.ts` (if needed)
- Rebuild: `web/`

**Interfaces:**
- Produces: generate payload includes `duration: number`; never sends `max_scenes`

- [ ] **Step 1: Add duration state + control**

Defaults by format:
- narrative: `90` (landscape) / `45` when aspect is `9:16`
- dialogue: `75`
- quizverse comment: `30`
- quizverse reveal: `max(60, questionCount * 20 + 10)`

UI: number input or select (e.g. 30 / 45 / 60 / 75 / 90 / 120 / 180). Label: “Duration (seconds)”. No max-scenes field.

- [ ] **Step 2: Include in submit payload**

```ts
generateVideo({
  idea: trimmed,
  style,
  aspect_ratio: aspect,
  duration,
  language,
  voice: ...,
  format,
  ...(format === "quizverse" ? { quiz_mode: quizMode, question_count: questionCount } : {}),
})
```

When format/aspect/quiz mode changes, update duration default only if user hasn’t manually edited (optional simplicity: always reset default on format change).

- [ ] **Step 3: Build**

```bash
cd frontend && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src web
git commit -m "feat: restore create-form duration; keep max scenes auto"
```

---

### Task 5: Snappier compose motion for short-form / dialogue

**Files:**
- Modify: `src/youtube_pipeline/video/ffmpeg_composer.py`
- Test: `tests/test_shot_synced_compose.py` (new)

**Interfaces:**
- Consumes: `script.format`, `self.aspect_ratio`
- Produces: shorter per-clip fade edges for dialogue and `9:16`; keep existing 6 Ken Burns patterns (already varied by `scene_index % 6`)

- [ ] **Step 1: Failing test**

```python
def test_edge_fade_shorter_for_dialogue_vertical():
    from youtube_pipeline.video.ffmpeg_composer import FFmpegComposer
    c = FFmpegComposer(aspect_ratio="9:16")
    # Extract helper or call a small pure function:
    # _clip_edge_fade_seconds(duration, *, format, aspect_ratio, settings)
    edge = c._clip_edge_fade_seconds(4.0, format="dialogue", aspect_ratio="9:16")
    assert edge <= 0.22
    wide = c._clip_edge_fade_seconds(4.0, format="narrative", aspect_ratio="16:9")
    assert wide >= edge
```

- [ ] **Step 2: Extract + implement**

```python
def _clip_edge_fade_seconds(
    self,
    duration: float,
    *,
    format: str = "narrative",
    aspect_ratio: str | None = None,
) -> float:
    base = float(getattr(self.settings, "scene_crossfade_seconds", 0.45) or 0.45)
    factor = 0.7
    aspect = aspect_ratio or self.aspect_ratio
    if format == "dialogue" or aspect == "9:16":
        factor = 0.45
        base = min(base, 0.35)
    edge = min(0.35, max(0.08, base * factor), max(0.05, duration * 0.18))
    return edge
```

Use it in `_render_scene_clip` instead of the inline formula. Pass `format` from `self.script.format` / assemble context (composer already has script or can read from scene pack — use existing assemble path fields).

- [ ] **Step 3: PASS + commit**

```bash
pytest tests/test_shot_synced_compose.py -q
git add src/youtube_pipeline/video/ffmpeg_composer.py tests/test_shot_synced_compose.py
git commit -m "feat: snappier ken-burns fades for dialogue shorts"
```

---

### Task 6: Soft-fail autofill + smoke regression

**Files:**
- Modify: `src/youtube_pipeline/assets/hitl_workspace.py` (only if autofill already aborts entire job on first failure — make per-scene continue)
- Test: `tests/test_dialogue_e2e_smoke.py`
- Test: `tests/test_image_aspect.py` (optional continue-on-error)

**Interfaces:**
- Produces: Dialogue smoke asserts `len(scenes) == len(lines)` after generate path

- [ ] **Step 1: Update smoke**

Mocked dialogue generate → waiting_for_assets workspace with scene count equal to line count.

- [ ] **Step 2: Autofill resilience**

If `auto_fill_scene_images` stops on first error, change to collect errors per scene, continue remaining scenes, return `{filled, failed, errors}`. Do not change successful path behavior.

- [ ] **Step 3: Run slice**

```bash
pytest tests/test_dialogue_beats.py tests/test_dialogue_generator.py tests/test_auto_scene_budget.py tests/test_dialogue_api.py tests/test_shot_synced_compose.py tests/test_dialogue_e2e_smoke.py tests/test_quiz_e2e_smoke.py tests/test_dialogue_tts.py tests/test_nameplate_overlays.py -q
```

- [ ] **Step 4: Commit**

```bash
git add src/youtube_pipeline/assets/hitl_workspace.py tests/test_dialogue_e2e_smoke.py
git commit -m "test: shot-synced dialogue scenes and autofill resilience"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Dialogue 1 image per line | 1, 2 |
| Scene duration = line VO | already TTS; verified in 6 |
| Manual duration create UX | 4 |
| Auto max scenes | 3 |
| Denser narrative / quiz budgets | 3 |
| Varied Ken Burns + snappier fades | 5 (patterns exist; fades tuned) |
| No AI video | global |
| Soft-fail image gen | 6 |
| Quiz/narrative regression | 6 |

## Placeholder scan

None intentional. Budget formulas above are normative for implementers; adjust only with test updates.
