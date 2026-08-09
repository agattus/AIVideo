# Quality Review Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a hybrid quality gate (script rubric + timing sanity + image aptness) for all formats, with one auto-retry per stage and a Studio checklist that blocks Assemble until pass or override.

**Architecture:** New `youtube_pipeline/quality/` package owns review models, LLM script critique/rewrite, deterministic timing checks, and image aptness. Orchestrator writes `quality_review.json` after script and TTS. HITL/API expose review + approve/regen; assemble refuses unless gate clear. JobStudio Quality panel mirrors checklist.

**Tech Stack:** Python 3.12, Pydantic, existing LLM provider (Groq/Gemini), optional Gemini vision for images, FastAPI, React/Vite studio, pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-09-quality-review-gate-design.md`
- Hybrid: **one** auto-retry per stage; then `needs_approval`
- Fail threshold: any rubric/aptness score **&lt; 3**
- Formats: narrative, quizverse, dialogue
- Timing checks are deterministic (no LLM)
- Assemble blocked until all rows `pass` **or** overridden
- Soft-continue Phase 1 even when script/timing need approval (still reach Studio)
- No final-MP4 video-model watch in v1
- Branch: continue on `feat/dialogue-format` unless asked otherwise

## File map

| File | Responsibility |
|------|----------------|
| `src/youtube_pipeline/quality/__init__.py` | Public exports |
| `src/youtube_pipeline/quality/models.py` | Pydantic review document + statuses |
| `src/youtube_pipeline/quality/store.py` | Read/write `quality_review.json` |
| `src/youtube_pipeline/quality/script_review.py` | LLM critique + one rewrite |
| `src/youtube_pipeline/quality/timing_review.py` | Deterministic VO/caption checks |
| `src/youtube_pipeline/quality/image_review.py` | Aptness score + one regen |
| `src/youtube_pipeline/quality/gate.py` | `assemble_allowed(review) -> bool` |
| `src/youtube_pipeline/orchestrator.py` | Call script + timing reviews in Phase 1 |
| `src/youtube_pipeline/assets/hitl_workspace.py` | Expose review; image review helper |
| `src/youtube_pipeline/api/schemas.py` | Workspace + approve payloads |
| `src/youtube_pipeline/api/main.py` | Approve / regen endpoints; assemble gate |
| `frontend/src/api/types.ts`, `client.ts` | Types + API calls |
| `frontend/src/components/JobStudio.tsx` | Quality panel + Assemble disable |
| `tests/test_quality_*.py` | Unit + gate tests |

---

### Task 1: Quality review models + store

**Files:**
- Create: `src/youtube_pipeline/quality/__init__.py`
- Create: `src/youtube_pipeline/quality/models.py`
- Create: `src/youtube_pipeline/quality/store.py`
- Create: `src/youtube_pipeline/quality/gate.py`
- Test: `tests/test_quality_store.py`

**Interfaces:**
- Produces:
  - `ReviewStatus = Literal["pass", "needs_approval", "overridden", "pending"]`
  - `QualityReview` pydantic model matching spec JSON shape
  - `load_quality_review(run_dir) -> QualityReview`
  - `save_quality_review(run_dir, review) -> Path`
  - `assemble_allowed(review: QualityReview) -> bool` — True iff every of script/timing/image is `pass` or `overridden`

- [ ] **Step 1: Failing tests**

```python
def test_assemble_allowed_requires_pass_or_override():
    from youtube_pipeline.quality.gate import assemble_allowed
    from youtube_pipeline.quality.models import QualityReview, StageReview

    review = QualityReview()
    assert assemble_allowed(review) is False  # pending defaults

    review.script_review.status = "pass"
    review.timing_review.status = "pass"
    review.image_review.status = "needs_approval"
    assert assemble_allowed(review) is False

    review.image_review.status = "overridden"
    assert assemble_allowed(review) is True


def test_round_trip_quality_review_json(tmp_path):
    from youtube_pipeline.quality.models import QualityReview
    from youtube_pipeline.quality.store import load_quality_review, save_quality_review

    review = QualityReview()
    review.script_review.status = "pass"
    review.script_review.scores = {"idea_fit": 4, "hook": 5, "ending": 4, "pacing_emotion": 3, "format_rules": 5}
    save_quality_review(tmp_path, review)
    loaded = load_quality_review(tmp_path)
    assert loaded.script_review.status == "pass"
    assert loaded.script_review.scores["hook"] == 5
```

- [ ] **Step 2: Implement models/store/gate**

Default each stage to `status="pending"`. `approvals` dict with script/timing/images bools. When status set to `overridden`, set matching approval True.

- [ ] **Step 3: PASS + commit**

```bash
pytest tests/test_quality_store.py -q
git add src/youtube_pipeline/quality tests/test_quality_store.py
git commit -m "feat: quality review models, store, and assemble gate"
```

---

### Task 2: Script LLM critique + one rewrite

**Files:**
- Create: `src/youtube_pipeline/quality/script_review.py`
- Test: `tests/test_quality_script_review.py`

**Interfaces:**
- Consumes: `VideoScript`, `PipelineRequest`, LLM via existing settings (mirror `ScriptEngine` call pattern or inject callable)
- Produces:
  - `critique_script(script, request, *, llm_call) -> StageReview` with scores + issues
  - `rewrite_script_once(script, request, critique, *, generate_fn) -> VideoScript`
  - `run_script_quality_gate(script, request, *, critique_fn, rewrite_fn) -> tuple[VideoScript, StageReview]`  
    If critique fails: rewrite once, re-critique; if still fail → `needs_approval`, else `pass`. `retries` 0 or 1.

Rubric keys exactly: `idea_fit`, `hook`, `ending`, `pacing_emotion`, `format_rules`. Fail if any score &lt; 3 or missing.

- [ ] **Step 1: Failing mocked tests**

```python
def test_run_script_quality_gate_retries_once_then_needs_approval():
    # critique_fn returns fail then fail; rewrite called once; status needs_approval; retries==1

def test_run_script_quality_gate_passes_after_rewrite():
    # critique fail then pass; status pass; retries==1
```

- [ ] **Step 2: Implement critique JSON schema + parse**

Prompt the LLM for JSON only. On parse failure, treat as fail with issue `"critique_parse_error"`.

- [ ] **Step 3: PASS + commit**

```bash
pytest tests/test_quality_script_review.py -q
git add src/youtube_pipeline/quality/script_review.py tests/test_quality_script_review.py
git commit -m "feat: LLM script quality critique with one rewrite"
```

---

### Task 3: Wire script gate into orchestrator

**Files:**
- Modify: `src/youtube_pipeline/orchestrator.py` (after `script_engine.generate`, before TTS)
- Test: `tests/test_quality_orchestrator_hook.py` (mock script engine + critique)

**Interfaces:**
- After generate + dialogue/quiz sidecars: call `run_script_quality_gate`; if rewritten script returned, overwrite `script.json` / dialogue sidecars; `save_quality_review` with script stage.

- [ ] **Step 1: Failing test** — mocked generate returns weak script; gate rewrite replaces title/scenes; `quality_review.json` exists with retries.

- [ ] **Step 2: Implement hook** — never raise out of Phase 1 on `needs_approval`; log issues.

- [ ] **Step 3: PASS + commit**

```bash
pytest tests/test_quality_orchestrator_hook.py -q
git add src/youtube_pipeline/orchestrator.py tests/test_quality_orchestrator_hook.py
git commit -m "feat: run script quality gate before TTS"
```

---

### Task 4: Deterministic timing review

**Files:**
- Create: `src/youtube_pipeline/quality/timing_review.py`
- Modify: `src/youtube_pipeline/orchestrator.py` (after TTS)
- Test: `tests/test_quality_timing_review.py`

**Interfaces:**
- Produces: `review_timing(*, script: VideoScript, timing: dict, duration_seconds: float, target_duration_seconds: int | None) -> StageReview`

Checks (fail → issues list, status `needs_approval`; else `pass`):
1. If `target_duration_seconds`: `abs(duration - target) / target <= 0.35`
2. Every scene `duration > 0`
3. If `script.format == "dialogue"`: `len(script.scenes) == len(script.lines)`
4. Word/caption span: last word `end` >= `0.85 * duration_seconds` when words present

- [ ] **Step 1: Unit tests** for each check  
- [ ] **Step 2: Orchestrator writes timing_review into quality_review.json**  
- [ ] **Step 3: PASS + commit**

```bash
pytest tests/test_quality_timing_review.py -q
git add src/youtube_pipeline/quality/timing_review.py src/youtube_pipeline/orchestrator.py tests/test_quality_timing_review.py
git commit -m "feat: deterministic timing quality review after TTS"
```

---

### Task 5: Image aptness + one regen

**Files:**
- Create: `src/youtube_pipeline/quality/image_review.py`
- Modify: `src/youtube_pipeline/assets/hitl_workspace.py` (call after autofill / expose helper)
- Test: `tests/test_quality_image_review.py`

**Interfaces:**
- Produces:
  - `score_scene_aptness(scene, image_path, *, vision_fn | text_fn) -> int` (1–5)
  - `run_image_quality_gate(run_dir, *, regenerate_fn) -> StageReview`  
    For each scene with image: score; if &lt; 3 and retries[scene_id]==0: regen once and rescore; collect fails → `needs_approval` else `pass`.

Vision path: if `GEMINI_API_KEY` and settings allow, send image + prompt/narration; else text-only: score consistency of `visual_prompt` vs `script_text` via LLM (no bytes).

- [ ] **Step 1: Mocked tests** — weak scene regens once; persistent fail listed  
- [ ] **Step 2: Hook from `auto_fill_scene_images` return path and/or `workspace_status` lazy run if image_review pending  
- [ ] **Step 3: PASS + commit**

```bash
pytest tests/test_quality_image_review.py -q
git add src/youtube_pipeline/quality/image_review.py src/youtube_pipeline/assets/hitl_workspace.py tests/test_quality_image_review.py
git commit -m "feat: image aptness review with one regen"
```

---

### Task 6: API — expose review, approve, regen, assemble gate

**Files:**
- Modify: `src/youtube_pipeline/api/schemas.py`
- Modify: `src/youtube_pipeline/api/main.py`
- Modify: `src/youtube_pipeline/assets/hitl_workspace.py` (`workspace_status` includes `quality_review`)
- Test: `tests/test_quality_api.py`

**Interfaces:**
- `GET workspace` includes `quality_review` + `assemble_allowed: bool`
- `POST /api/v1/jobs/{id}/quality/approve` body `{ "stage": "script"|"timing"|"images" }` → set overridden
- `POST /api/v1/jobs/{id}/quality/regen-script` → re-run script generate + gate (async/thread like other jobs) — v1 may sync with timeout; prefer reuse existing job mutate patterns
- `POST /api/v1/jobs/{id}/quality/regen-images` → regen scenes listed in image_review fails
- Assemble / resume: if not `assemble_allowed`, HTTP 409 with review summary

- [ ] **Step 1: API tests with TestClient**  
- [ ] **Step 2: Implement**  
- [ ] **Step 3: PASS + commit**

```bash
pytest tests/test_quality_api.py -q
git add src/youtube_pipeline/api src/youtube_pipeline/assets/hitl_workspace.py tests/test_quality_api.py
git commit -m "feat: quality review API and assemble gate"
```

---

### Task 7: Frontend Quality panel

**Files:**
- Modify: `frontend/src/api/types.ts`, `client.ts`
- Modify: `frontend/src/components/JobStudio.tsx`
- Rebuild: `web/`

**Interfaces:**
- Quality collapsible: three rows with status badges; issue list; buttons Approve / Regen script / Regen weak images
- Assemble button: `disabled={!workspace.assemble_allowed || assembling}` (in addition to scenes ready)
- Show hint when blocked: “Resolve or approve quality checks”

- [ ] **Step 1: Wire types + client methods**  
- [ ] **Step 2: UI panel matching existing Cast/Quiz section style**  
- [ ] **Step 3: `npm run build` + commit**

```bash
cd frontend && npm run build
git add frontend/src web
git commit -m "feat: Studio quality checklist and assemble gate UI"
```

---

### Task 8: Smoke + regression slice

**Files:**
- Test: `tests/test_quality_e2e_smoke.py`
- Update any assemble tests that assume assemble always works when images ready

- [ ] **Step 1: Smoke** — mocked LLM critique pass → assemble_allowed True after images pass; fail path needs override  
- [ ] **Step 2: Run**

```bash
pytest tests/test_quality_store.py tests/test_quality_script_review.py tests/test_quality_timing_review.py tests/test_quality_image_review.py tests/test_quality_api.py tests/test_quality_e2e_smoke.py tests/test_dialogue_e2e_smoke.py tests/test_quiz_e2e_smoke.py -q
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_quality_e2e_smoke.py
git commit -m "test: quality review gate smoke and assemble regression"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Script rubric + one rewrite | 2, 3 |
| Timing deterministic checks | 4 |
| Image aptness + one regen | 5 |
| Studio checklist + Assemble gate | 6, 7 |
| quality_review.json | 1, 3–5 |
| All formats | 2–5 (format_rules + dialogue count) |
| Hybrid retry | 2, 5 |
| Override approvals | 1, 6, 7 |

## Placeholder scan

None intentional. Regen-script endpoint may reuse Phase-1 thread patterns from existing voice regen; implementer should mirror `cast/voices` / voiceover regen style rather than invent a new job system.
