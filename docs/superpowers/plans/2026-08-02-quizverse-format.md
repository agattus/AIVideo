# Quizverse Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `quizverse` content format with Comment mode (Shorts, no answer reveal) and Reveal mode (5s → 10s → 5s per question), without breaking existing narrative jobs.

**Architecture:** Keep `style` as visual/BGM only. Add `format` + `quiz_mode` + `question_count` on the request. LLM returns `questions[]`; a pure expander turns them into linear `SceneData` beats (`hook` / `question` / `timer` / `reveal` / `cta`). TTS skips silent timer beats (uses `hold_seconds`). FFmpeg compose burns question/countdown/reveal/CTA overlays per `beat_type`. Studio exposes answer key + community-post draft for Comment mode.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, Edge-TTS, FFmpeg + Pillow overlays, React/Vite studio UI, pytest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-02-quizverse-format-design.md`
- Default `format=narrative` — existing jobs must behave identically when format omitted
- Comment mode: answer never in VO, captions, or burn-in
- Reveal timings: question 5s, timer 10s, reveal 5s (~20s/question)
- Comment think timer: 3–5s (use 4s), not 10s
- Comment `question_count` clamp 1–5 (default 1); Reveal clamp 3–15 (default 5)
- No YouTube auto-post; draft text only
- Soft-fail overlays/SFX; assemble must still produce a video

## File map

| File | Responsibility |
|------|----------------|
| `src/youtube_pipeline/models.py` | `VideoFormat`, `QuizMode`, beat fields on `SceneData`, request fields |
| `src/youtube_pipeline/quiz/beats.py` | `expand_quiz_questions(...)` → `list[SceneData]` |
| `src/youtube_pipeline/quiz/drafts.py` | `build_community_post_draft(...)` |
| `src/youtube_pipeline/script_engine/quiz_prompts.py` | Quizverse system/user prompts |
| `src/youtube_pipeline/script_engine/generator.py` | Branch generate path for quizverse |
| `src/youtube_pipeline/script_engine/schema.py` | Quiz LLM JSON schema |
| `src/youtube_pipeline/audio/tts.py` | Honor `hold_seconds`; silent timer beats |
| `src/youtube_pipeline/video/quiz_overlays.py` | Pillow cards + countdown frames |
| `src/youtube_pipeline/video/ffmpeg_composer.py` | Apply overlays by `beat_type` |
| `src/youtube_pipeline/api/schemas.py` | API request/workspace fields |
| `src/youtube_pipeline/api/tasks.py` | Map new fields into `PipelineRequest` |
| `src/youtube_pipeline/assets/hitl_workspace.py` | Expose answer key + community draft |
| `frontend/src/api/types.ts` + `client.ts` | Types + generate payload |
| `frontend/src/components/GenerateForm.tsx` | Format / mode / count UI |
| `frontend/src/components/JobStudio.tsx` | Answer key + copy draft |
| `tests/test_quiz_beats.py` | Expansion + leak guards |
| `tests/test_quiz_tts_holds.py` | Timer silence / hold_seconds |
| `tests/test_quiz_api.py` | Generate request accepts format fields |

---

### Task 1: Models — format enums + beat fields

**Files:**
- Modify: `src/youtube_pipeline/models.py`
- Test: `tests/test_quiz_models.py`

**Interfaces:**
- Produces: `VideoFormat`, `QuizMode`, `BeatType` enums; `SceneData` optional quiz fields; `PipelineRequest.format/quiz_mode/question_count`; `VideoScript.format/quiz_mode`

- [ ] **Step 1: Write failing model tests**

```python
# tests/test_quiz_models.py
from youtube_pipeline.models import (
    BeatType,
    PipelineRequest,
    QuizMode,
    SceneData,
    VideoFormat,
    VideoScript,
)

def test_pipeline_request_defaults_narrative():
    req = PipelineRequest(idea="Ancient myths quiz")
    assert req.format == VideoFormat.NARRATIVE
    assert req.quiz_mode is None
    assert req.question_count is None

def test_scene_data_timer_allows_empty_script_text():
    scene = SceneData(
        scene_id=0,
        script_text="",
        visual_prompt="dark quiz background",
        beat_type=BeatType.TIMER,
        hold_seconds=10.0,
        quiz_index=0,
        question="Who?",
        answer="A",
    )
    assert scene.beat_type == BeatType.TIMER
    assert scene.script_text == ""
    assert scene.hold_seconds == 10.0

def test_narrative_scene_still_requires_script_text():
    import pytest
    with pytest.raises(Exception):
        SceneData(scene_id=0, script_text="", visual_prompt="x")
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `pytest tests/test_quiz_models.py -v`  
Expected: FAIL (enums/fields missing)

- [ ] **Step 3: Implement models**

Add to `models.py`:

```python
class VideoFormat(str, Enum):
    NARRATIVE = "narrative"
    QUIZVERSE = "quizverse"

class QuizMode(str, Enum):
    COMMENT = "comment"
    REVEAL = "reveal"

class BeatType(str, Enum):
    HOOK = "hook"
    INTRO = "intro"
    QUESTION = "question"
    TIMER = "timer"
    REVEAL = "reveal"
    CTA = "cta"
    OUTRO = "outro"
    NARRATION = "narration"  # default for narrative scenes
```

On `SceneData`:
- `beat_type: BeatType = BeatType.NARRATION`
- `quiz_index: int | None = None`
- `question: str = ""`
- `choices: list[str] = Field(default_factory=list)`
- `answer: str = ""`
- `explain: str = ""`
- `hold_seconds: float | None = None`
- Relax `_reject_blank` / `script_text` so empty string is allowed when `beat_type == BeatType.TIMER` (use a model_validator after fields are set).

On `PipelineRequest`:
- `format: VideoFormat = VideoFormat.NARRATIVE`
- `quiz_mode: QuizMode | None = None`
- `question_count: int | None = Field(default=None, ge=1, le=15)`

On `VideoScript`:
- `format: str = "narrative"`
- `quiz_mode: str | None = None`

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/test_quiz_models.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/youtube_pipeline/models.py tests/test_quiz_models.py
git commit -m "feat: add Quizverse format and beat fields to models"
```

---

### Task 2: Beat expander + community draft (pure functions)

**Files:**
- Create: `src/youtube_pipeline/quiz/__init__.py`
- Create: `src/youtube_pipeline/quiz/beats.py`
- Create: `src/youtube_pipeline/quiz/drafts.py`
- Test: `tests/test_quiz_beats.py`

**Interfaces:**
- Consumes: `QuizMode`, `SceneData`, `BeatType` from models
- Produces:
  - `expand_quiz_questions(questions: list[dict], *, mode: QuizMode, language: str = "en") -> list[SceneData]`
  - `build_community_post_draft(title: str, questions: list[dict]) -> str`
  - `assert_no_answer_leak(scenes: list[SceneData], questions: list[dict]) -> None`

- [ ] **Step 1: Write failing expander tests**

```python
# tests/test_quiz_beats.py
from youtube_pipeline.models import BeatType, QuizMode
from youtube_pipeline.quiz.beats import assert_no_answer_leak, expand_quiz_questions
from youtube_pipeline.quiz.drafts import build_community_post_draft

QUESTIONS = [
    {
        "question": "Who is the king of the Greek gods?",
        "choices": ["Apollo", "Zeus", "Hades"],
        "answer": "Zeus",
        "explain": "Zeus rules Olympus.",
    }
]

def test_reveal_mode_timings():
    scenes = expand_quiz_questions(QUESTIONS, mode=QuizMode.REVEAL)
    types = [s.beat_type for s in scenes]
    assert BeatType.QUESTION in types
    assert BeatType.TIMER in types
    assert BeatType.REVEAL in types
    assert BeatType.CTA not in types
    q = next(s for s in scenes if s.beat_type == BeatType.QUESTION)
    t = next(s for s in scenes if s.beat_type == BeatType.TIMER)
    r = next(s for s in scenes if s.beat_type == BeatType.REVEAL)
    assert q.hold_seconds == 5.0
    assert t.hold_seconds == 10.0
    assert r.hold_seconds == 5.0
    assert t.script_text == ""
    assert "Zeus" in r.script_text

def test_comment_mode_hides_answer_from_speech_and_has_cta():
    scenes = expand_quiz_questions(QUESTIONS, mode=QuizMode.COMMENT)
    assert any(s.beat_type == BeatType.CTA for s in scenes)
    assert not any(s.beat_type == BeatType.REVEAL for s in scenes)
    spoken = " ".join(s.script_text for s in scenes)
    assert "Zeus" not in spoken
    assert_no_answer_leak(scenes, QUESTIONS)

def test_community_draft_includes_answers_for_creator():
    draft = build_community_post_draft("Greek Quiz", QUESTIONS)
    assert "Zeus" in draft
    assert "comments" in draft.lower()
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/test_quiz_beats.py -v`

- [ ] **Step 3: Implement expander + draft**

Constants in `beats.py`:
- Reveal: Q=5, T=10, R=5
- Comment: Q=4, T=4, CTA=3, HOOK=2

`expand_quiz_questions`:
- Comment: hook scene → for each q: question + timer → final cta  
- Reveal: for each q: question + timer + reveal  
- Assign contiguous `scene_id`  
- `visual_prompt` derived from question text (simple template)  
- Question `script_text` = question (+ choices read aloud optionally)  
- Reveal `script_text` = f"{answer}. {explain}"  
- CTA `script_text` = fixed English or language-aware one-liner (v1 English template OK if `language=="en"`, else English + note)

`assert_no_answer_leak`: for Comment mode scenes, ensure no answer substring appears in `script_text` / burned display fields (`question` ok; `answer` field may exist on scene for studio but must not be in `script_text`).

`build_community_post_draft`: title + numbered Q&A + “Reply tomorrow” wording.

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/test_quiz_beats.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/youtube_pipeline/quiz tests/test_quiz_beats.py
git commit -m "feat: expand Quizverse questions into timed beats"
```

---

### Task 3: Quiz prompts + generator branch

**Files:**
- Create: `src/youtube_pipeline/script_engine/quiz_prompts.py`
- Modify: `src/youtube_pipeline/script_engine/schema.py`
- Modify: `src/youtube_pipeline/script_engine/generator.py`
- Test: `tests/test_quiz_generator.py`

**Interfaces:**
- Consumes: `expand_quiz_questions`, `PipelineRequest.format`
- Produces: `ScriptEngine.generate` returns `VideoScript` with quiz beats when format is quizverse

- [ ] **Step 1: Write failing generator unit test with mocked LLM**

```python
# tests/test_quiz_generator.py
from unittest.mock import MagicMock
from youtube_pipeline.models import PipelineRequest, QuizMode, VideoFormat
from youtube_pipeline.script_engine.generator import ScriptEngine

def test_quizverse_generate_expands_beats(monkeypatch):
    engine = ScriptEngine.__new__(ScriptEngine)
    engine.settings = MagicMock()
    payload = {
        "title": "Greek Gods Quiz",
        "questions": [
            {
                "question": "Who is the king of the Greek gods?",
                "choices": ["Apollo", "Zeus"],
                "answer": "Zeus",
                "explain": "Zeus rules Olympus.",
            }
        ],
    }
    monkeypatch.setattr(engine, "_call_llm_json", lambda *a, **k: payload)
    req = PipelineRequest(
        idea="Greek gods",
        format=VideoFormat.QUIZVERSE,
        quiz_mode=QuizMode.REVEAL,
        question_count=1,
        max_scenes=3,
    )
    # If generate signature needs settings in __init__, construct properly and only mock LLM.
    script = engine.generate(req)
    assert script.format == "quizverse"
    assert len(script.scenes) >= 3
    assert any(s.beat_type.value == "timer" for s in script.scenes)
```

(Adapt construction to match real `ScriptEngine.__init__`.)

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

`quiz_prompts.py`:
- `build_quiz_system_prompt(mode, language, question_count)`
- `build_quiz_user_prompt(idea, mode, question_count, language)`
- Require exactly `question_count` items; each with question, optional choices (2–4), answer, explain (≤25 words)
- Comment mode: still require answer/explain for studio key

`schema.py`: add `QUIZ_SCRIPT_SCHEMA` with `title` + `questions[]`.

`generator.py`:
- If `request.format == VideoFormat.QUIZVERSE`:
  - Normalize mode (default comment) and clamp counts
  - Call LLM with quiz schema/prompts
  - `scenes = expand_quiz_questions(...)`
  - `full_script = " ".join(s.script_text for s in scenes if s.script_text.strip())` or `" ".join(questions)`
  - Return `VideoScript(..., format="quizverse", quiz_mode=mode.value, scenes=scenes)`
- Else existing path unchanged

Also persist `questions` raw list into run dir later via orchestrator (`quiz_questions.json`) — add write in generator return metadata or orchestrator Task 5.

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/test_quiz_generator.py tests/test_quiz_beats.py tests/test_quiz_models.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/youtube_pipeline/script_engine tests/test_quiz_generator.py
git commit -m "feat: generate Quizverse scripts from questions[]"
```

---

### Task 4: TTS respects hold_seconds + silent timers

**Files:**
- Modify: `src/youtube_pipeline/audio/tts.py`
- Test: `tests/test_quiz_tts_holds.py`

**Interfaces:**
- Consumes: `SceneData.hold_seconds`, `beat_type`
- Produces: voiceover where timer beats contribute exact silence duration; question/reveal speech padded/trimmed toward `hold_seconds` when set

- [ ] **Step 1: Failing test**

```python
# tests/test_quiz_tts_holds.py
from pathlib import Path
from youtube_pipeline.audio.tts import AudioEngine
from youtube_pipeline.models import BeatType, SceneData, VideoScript

def test_timer_beat_uses_hold_seconds_silence(tmp_path, monkeypatch):
    from config.settings import Settings, TTSProvider
    settings = Settings(tts_provider=TTSProvider.EDGE_TTS, _env_file=None, openai_api_key="x")
    monkeypatch.setattr(AudioEngine, "_validate_config", lambda self: None)
    engine = AudioEngine(settings)

    def fake_edge(self, text, output_path, *, voice=None):
        output_path.write_bytes(b"ID3" + b"\0" * 200)

    monkeypatch.setattr(AudioEngine, "_synthesize_edge_tts", fake_edge)
    monkeypatch.setattr(AudioEngine, "_make_silence_mp3", lambda self, dest, *, pause_ms, ffmpeg=None: dest.write_bytes(b"SIL"))
    monkeypatch.setattr(
        AudioEngine,
        "_concat_mp3_with_silence",
        lambda self, clips, dest, *, pause_ms: dest.write_bytes(b"JOIN"),
    )
    monkeypatch.setattr(engine, "_probe_duration_seconds", lambda path: 4.0 if "scene_" in path.name else 13.0)

    script = VideoScript(
        title="Q",
        full_script="Who?",
        style="cinematic",
        format="quizverse",
        scenes=[
            SceneData(scene_id=0, script_text="Who?", visual_prompt="q", beat_type=BeatType.QUESTION, hold_seconds=5, question="Who?"),
            SceneData(scene_id=1, script_text="", visual_prompt="t", beat_type=BeatType.TIMER, hold_seconds=4, question="Who?", answer="A"),
            SceneData(scene_id=2, script_text="Comment below", visual_prompt="c", beat_type=BeatType.CTA, hold_seconds=3),
        ],
    )
    result = engine.synthesize(script, tmp_path / "audio", use_per_scene_text=True)
    assert result.audio_path.exists()
    # Timer duration must come from hold_seconds in timing scenes
    timer = next(s for s in result.timing["scenes"] if s.get("beat_type") == "timer" or True)
    # Prefer asserting speech_duration list / scene durations include ~4s timer
    assert any(abs(s.duration - 4.0) < 0.2 for s in result.script.scenes if s.beat_type == BeatType.TIMER)
```

(Tighten asserts to match implementation details while writing.)

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement**

In per-scene Edge path (and one-shot path when `hold_seconds` set):
- If `beat_type == TIMER` or not `script_text.strip()`: write silence of `hold_seconds` via `_make_silence_mp3` (ms = int(hold*1000))
- Else synthesize speech; if `hold_seconds` and speech shorter, pad silence after; if longer, keep speech length (hold is minimum for timer only — for question/reveal prefer max(speech, hold) by padding)
- Prefer **authoritative** `hold_seconds` for timer; for spoken beats use `max(probed, hold_seconds)` with trailing silence pad so on-screen timer/question cards stay aligned
- Inter-scene pause for quizverse: use `0` ms (beats already include timing) when `script.format == "quizverse"`

- [ ] **Step 4: PASS + commit**

```bash
git add src/youtube_pipeline/audio/tts.py tests/test_quiz_tts_holds.py
git commit -m "feat: honor quiz hold_seconds and silent timer beats in TTS"
```

---

### Task 5: Quiz overlays + composer wiring

**Files:**
- Create: `src/youtube_pipeline/video/quiz_overlays.py`
- Modify: `src/youtube_pipeline/video/ffmpeg_composer.py`
- Test: `tests/test_quiz_overlays.py`

**Interfaces:**
- Produces: `render_quiz_overlay_png(beat: SceneData, *, width, height, t_within_beat: float) -> Path | None`
- Composer calls overlay path when `scene.beat_type` in question/timer/reveal/cta

- [ ] **Step 1: Failing overlay test**

```python
from pathlib import Path
from youtube_pipeline.models import BeatType, SceneData
from youtube_pipeline.video.quiz_overlays import render_quiz_card

def test_render_question_card(tmp_path: Path):
    scene = SceneData(
        scene_id=0,
        script_text="Who?",
        visual_prompt="bg",
        beat_type=BeatType.QUESTION,
        hold_seconds=5,
        question="Who is the king of the Greek gods?",
        choices=["Apollo", "Zeus"],
    )
    path = render_quiz_card(scene, dest=tmp_path / "q.png", width=1080, height=1920, countdown=None)
    assert path.exists()
    assert path.stat().st_size > 500

def test_render_countdown(tmp_path: Path):
    scene = SceneData(
        scene_id=1,
        script_text="",
        visual_prompt="bg",
        beat_type=BeatType.TIMER,
        hold_seconds=10,
        question="Who?",
    )
    path = render_quiz_card(scene, dest=tmp_path / "t.png", width=1080, height=1920, countdown=7)
    assert path.exists()
```

- [ ] **Step 2: Implement Pillow cards**

- Dark translucent panel, large title text, choices listed for question
- Timer: huge centered number
- Reveal: “ANSWER” label + answer + explain
- CTA: comment prompt
- Use existing font helper from `i18n.caption_font_for_language` when available

- [ ] **Step 3: Wire `FFmpegComposer._render_scene_clip`**

After Ken Burns base (or as overlay pass):
- If beat is quiz type, render PNG and overlay full-frame with ffmpeg `overlay`
- For TIMER beats: either one static mid-number PNG for v1 **or** regenerate per-second overlays (v1 acceptable: single PNG showing starting seconds, e.g. `10` — note in code comment; follow-up can animate). Prefer simple v1: burn text “Answer in the comments” on CTA; on timer show `int(ceil(hold_seconds))` once. Spec wants countdown — implement per-second if feasible with existing caption overlay loop; otherwise static number is OK for first merge with TODO comment referencing spec.

Minimum for merge: question card + reveal/CTA cards + timer showing remaining whole seconds via multi-overlay like captions (one PNG per second, timed).

- [ ] **Step 4: Tests PASS + commit**

```bash
git add src/youtube_pipeline/video/quiz_overlays.py src/youtube_pipeline/video/ffmpeg_composer.py tests/test_quiz_overlays.py
git commit -m "feat: burn Quizverse question, timer, reveal, and CTA overlays"
```

---

### Task 6: API + orchestrator persistence

**Files:**
- Modify: `src/youtube_pipeline/api/schemas.py`
- Modify: `src/youtube_pipeline/api/tasks.py`
- Modify: `src/youtube_pipeline/api/main.py` (generate only if needed)
- Modify: `src/youtube_pipeline/orchestrator.py`
- Modify: `src/youtube_pipeline/assets/hitl_workspace.py`
- Test: `tests/test_quiz_api.py`

**Interfaces:**
- `GenerateVideoRequest`: `format`, `quiz_mode`, `question_count`
- `WorkspaceResponse`: `format`, `quiz_mode`, `quiz_answer_key`, `community_post_draft`
- Orchestrator writes `quiz_questions.json` + draft after Phase 1

- [ ] **Step 1: API schema test**

```python
from youtube_pipeline.api.schemas import GenerateVideoRequest

def test_generate_request_accepts_quizverse():
    req = GenerateVideoRequest(
        idea="Greek gods quiz",
        format="quizverse",
        quiz_mode="comment",
        question_count=1,
        aspect_ratio="9:16",
    )
    assert req.format == "quizverse"
    assert req.quiz_mode == "comment"
```

- [ ] **Step 2: Map fields in `tasks.py` into `PipelineRequest`**

Clamp counts; if format quizverse and mode missing → `comment`; if narrative → ignore quiz fields.

- [ ] **Step 3: Orchestrator after script gen**

```python
if request.format == VideoFormat.QUIZVERSE:
    write_json(run_dir / "quiz_questions.json", questions_raw)
    write_json(run_dir / "community_post_draft.txt" is wrong — use .txt write)
```

Use plain text write for draft via `build_community_post_draft`.

- [ ] **Step 4: `workspace_status` exposes**

```python
"format": ...,
"quiz_mode": ...,
"quiz_answer_key": [...],
"community_post_draft": "...",
```

Load from `quiz_questions.json` / draft file / script scenes.

- [ ] **Step 5: Tests + commit**

```bash
git add src/youtube_pipeline/api src/youtube_pipeline/orchestrator.py src/youtube_pipeline/assets/hitl_workspace.py tests/test_quiz_api.py
git commit -m "feat: expose Quizverse fields on generate API and studio workspace"
```

---

### Task 7: Frontend create form + studio panels

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/components/GenerateForm.tsx`
- Modify: `frontend/src/components/JobStudio.tsx`
- Rebuild: `frontend` → `web/`

**Interfaces:**
- `GeneratePayload` includes `format?`, `quiz_mode?`, `question_count?`
- Workspace shows answer key + copy draft when `format === "quizverse"`

- [ ] **Step 1: Extend types + `generateVideo` body**

- [ ] **Step 2: GenerateForm UI**

- Select: Narrative | Quizverse  
- If Quizverse: Comment | Reveal; number input for question count  
- On Comment: set aspect default `9:16`  
- On Reveal: default `16:9`, question_count default 5  

- [ ] **Step 3: JobStudio section**

- New collapsible “Quiz” section when `workspace.format === "quizverse"`  
- List answer key  
- Button “Copy community post draft” via existing `copyText`  

- [ ] **Step 4: `npm run build` and commit web assets**

```bash
cd frontend && npm run build
git add frontend/src web
git commit -m "feat: Quizverse options in create form and studio answer key"
```

---

### Task 8: End-to-end smoke + regression

**Files:**
- Test: `tests/test_quiz_e2e_smoke.py` (mocked LLM + mocked ffmpeg where needed)

- [ ] **Step 1: Smoke test Comment path does not leak answer into caption timeline inputs**

Use expander + `scene_caption_timeline` on Comment scenes; assert answer absent.

- [ ] **Step 2: Run full quiz + narrative regression slice**

```bash
pytest tests/test_quiz_models.py tests/test_quiz_beats.py tests/test_quiz_generator.py tests/test_quiz_tts_holds.py tests/test_quiz_overlays.py tests/test_quiz_api.py tests/test_script_schema.py tests/test_edge_tts_engine.py -q
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_quiz_e2e_smoke.py
git commit -m "test: Quizverse smoke and narrative regression slice"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| `format` vs `style` | 1, 6, 7 |
| Comment mode beats + no reveal | 2, 3, 7 |
| Reveal 5/10/5 | 2, 4 |
| `questions[]` → beats | 2, 3 |
| TTS silent timers / holds | 4 |
| Overlays | 5 |
| Community draft + answer key | 2, 6, 7 |
| Create form UX | 7 |
| Narrative default / no regression | 1, 3, 8 |
| Soft-fail overlays | 5 |

## Placeholder scan

None intentional. Timer animation may ship as per-second PNGs in Task 5; if time-boxed, static countdown start value is explicitly allowed with a code comment pointing at the spec.
