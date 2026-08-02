# Scene Ambience + SFX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mix soft per-scene ambience loops and timed one-shot SFX from a bundled offline pack into the final FFmpeg assemble, with LLM tags + keyword fallback and a Studio ambience override.

**Architecture:** Extend `SceneData` with `ambience` + `sfx[]`. Tag via script LLM schema/prompts and `apply_sfx_fallback()`. At assemble, build an FFmpeg filter graph that mixes VO + BGM + scene-timed ambience + delayed one-shots. Bundle short pack files under `assets/sfx/` (generated with ffmpeg for v1/CI; LICENSE documents CC0 replacement sources).

**Tech Stack:** Python 3.12, Pydantic, FFmpeg (`ffmpeg_composer.py`), FastAPI workspace, React JobStudio, pytest.

## Global Constraints

- Soft-fail: missing/unknown SFX never fails assemble (skip that layer).
- VO volume `1.05`, BGM `0.10`, ambience `0.12`, one-shots `0.35` (match/extend current mux).
- Ambience tags only: `rain|wind|forest|city|ocean|fire|night|room|none`.
- Oneshot tags only: `thunder|footsteps|door|birds|crowd_cheer|whoosh`.
- Max 2 one-shots per scene; clamp `at` to `0.15–0.85`.
- Offline pack under `assets/sfx/`; no paid SFX APIs.
- No custom SFX upload in v1; Studio dropdown for ambience only.
- `SceneData` / `SceneSlot` use `extra="forbid"` — new fields must be explicit with defaults.
- Old scripts without tags must still assemble (`ambience=none`, `sfx=[]`).

## File Structure

| File | Responsibility |
|------|----------------|
| `assets/sfx/**` + `LICENSE.txt` | Bundled ambience/oneshot mp3s |
| `src/youtube_pipeline/audio/sfx_pack.py` | Resolve pack paths, tag enums, volumes |
| `src/youtube_pipeline/audio/sfx_tags.py` | Keyword fallback + normalize tags |
| `src/youtube_pipeline/models.py` | `SfxCue`, `SceneData.ambience`, `SceneData.sfx` |
| `src/youtube_pipeline/script_engine/schema.py` | JSON schema fields |
| `src/youtube_pipeline/script_engine/prompts.py` | Instruct LLM to emit tags |
| `src/youtube_pipeline/video/ffmpeg_composer.py` | Mix ambience/oneshots in `_mux_audio` |
| `src/youtube_pipeline/assets/hitl_workspace.py` | Expose tags; persist ambience override |
| `src/youtube_pipeline/api/schemas.py` + `main.py` | SceneSlot fields; PATCH ambience |
| `frontend/src/.../JobStudio.tsx` | Show tags + ambience dropdown |
| `tests/test_sfx_tags.py`, `tests/test_sfx_mux.py` | Unit coverage |

---

### Task 1: Bundled SFX pack (ffmpeg-generated placeholders)

**Files:**
- Create: `assets/sfx/LICENSE.txt`
- Create: `assets/sfx/ambiences/{rain,wind,forest,city,ocean,fire,night,room}.mp3`
- Create: `assets/sfx/oneshots/{thunder,footsteps,door,birds,crowd_cheer,whoosh}.mp3`
- Create: `scripts/generate_sfx_pack.py` (generator used once / in CI)

**Interfaces:**
- Produces: pack files on disk; `SFX_ROOT = repo/assets/sfx`

- [ ] **Step 1: Write generator script**

`scripts/generate_sfx_pack.py` — for each ambience, run ffmpeg to create ~12s mono mp3 of filtered noise (different filters per tag for variety); for each oneshot, ~0.6–1.2s tone/noise blip. Idempotent: skip if file exists and size > 1KB unless `--force`.

Example ambience command pattern:

```bash
ffmpeg -y -f lavfi -i "anoisesrc=color=pink:duration=12" -af "lowpass=f=800,volume=0.4" -ac 1 assets/sfx/ambiences/rain.mp3
```

Vary filters slightly per tag (highpass for wind, bandpass for city, etc.). Oneshots: short `sine`/`anoisesrc` with fade.

- [ ] **Step 2: Run generator**

Run: `python scripts/generate_sfx_pack.py`  
Expected: all 8 + 6 mp3 files exist.

- [ ] **Step 3: Write LICENSE.txt**

State files are synthetic placeholders for development; list recommended CC0 replacement sources (e.g. CC0 Sounds / Signature Sounds CC0 weather packs) for production polish.

- [ ] **Step 4: Commit**

```bash
git add assets/sfx scripts/generate_sfx_pack.py
git commit -m "feat: add bundled ambient and oneshot SFX pack"
```

---

### Task 2: Models + tag normalization + keyword fallback

**Files:**
- Create: `src/youtube_pipeline/audio/sfx_pack.py`
- Create: `src/youtube_pipeline/audio/sfx_tags.py`
- Modify: `src/youtube_pipeline/models.py` (`SceneData`)
- Modify: `src/youtube_pipeline/audio/__init__.py` if exports are used
- Test: `tests/test_sfx_tags.py`

**Interfaces:**
- Produces:

```python
AMBIENCE_TAGS = frozenset({...})
ONESHOT_TAGS = frozenset({...})

class SfxCue(BaseModel):
    tag: str
    at: float  # 0..1

# SceneData additions:
ambience: str = "none"
sfx: list[SfxCue] = Field(default_factory=list)

def normalize_ambience(raw: str | None) -> str: ...
def normalize_sfx(cues: list[Any] | None) -> list[SfxCue]: ...  # max 2, clamp at
def infer_sfx_from_text(script_text: str, visual_prompt: str = "") -> tuple[str, list[SfxCue]]: ...
def apply_sfx_fallback(scene: SceneData) -> SceneData: ...  # fill if none/empty
def resolve_ambience_path(tag: str, root: Path | None = None) -> Path | None: ...
def resolve_oneshot_path(tag: str, root: Path | None = None) -> Path | None: ...
```

- [ ] **Step 1: Failing tests**

```python
# tests/test_sfx_tags.py
from youtube_pipeline.audio.sfx_tags import infer_sfx_from_text, normalize_sfx, apply_sfx_fallback
from youtube_pipeline.models import SceneData, SfxCue

def test_rain_inference():
    amb, sfx = infer_sfx_from_text("Heavy rain on the roof", "wet streets")
    assert amb == "rain"
    assert any(c.tag == "thunder" for c in sfx) or amb == "rain"

def test_normalize_clamps_and_limits():
    cues = normalize_sfx([
        {"tag": "thunder", "at": 0.01},
        {"tag": "whoosh", "at": 0.99},
        {"tag": "door", "at": 0.5},
    ])
    assert len(cues) == 2
    assert cues[0].at >= 0.15
    assert cues[1].at <= 0.85

def test_apply_fallback_preserves_existing():
    scene = SceneData(
        scene_id=0,
        script_text="Rain falls",
        visual_prompt="storm",
        ambience="forest",
        sfx=[SfxCue(tag="birds", at=0.5)],
    )
    out = apply_sfx_fallback(scene)
    assert out.ambience == "forest"
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/test_sfx_tags.py -v`

- [ ] **Step 3: Implement models + sfx_pack + sfx_tags**

Add `SfxCue` and fields on `SceneData` with validators that coerce unknown ambience → `none` and drop unknown oneshot tags.

`infer_sfx_from_text`: simple keyword tables (case-insensitive). Example: if "rain"/"storm"/"drizzle" → ambience rain; if "thunder"/"lightning" add thunder cue at 0.45. Forest/jungle → forest + optional birds. City/street/traffic → city. Ocean/sea/beach/waves → ocean. Fire/campfire → fire. Night/midnight/moon → night. Wind/gale → wind. Else `none`.

`apply_sfx_fallback`: if ambience is missing/`none` and sfx empty, replace from inference; if ambience set but sfx empty, may still add inferred oneshots only when keywords match (keep simple: only fill when ambience is `none` and sfx empty).

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Commit**

```bash
git add src/youtube_pipeline/models.py src/youtube_pipeline/audio/sfx_pack.py src/youtube_pipeline/audio/sfx_tags.py tests/test_sfx_tags.py
git commit -m "feat: scene ambience/sfx models and keyword fallback"
```

---

### Task 3: Script schema + LLM prompts + post-parse fallback

**Files:**
- Modify: `src/youtube_pipeline/script_engine/schema.py`
- Modify: `src/youtube_pipeline/script_engine/prompts.py`
- Modify: `src/youtube_pipeline/script_engine/generator.py` (call `apply_sfx_fallback` on each scene after parse)
- Test: extend `tests/test_script_schema.py` / `tests/test_models.py`

**Interfaces:**
- Consumes: `apply_sfx_fallback`, `normalize_*`
- Produces: scripts with ambience/sfx populated

- [ ] **Step 1: Failing schema test**

Assert `video_script_json_schema()` scene items include `ambience` and `sfx` properties; required list includes them (or defaults applied in parser if not required — prefer required with defaults in LLM instructions; for OpenAI strict mode all properties must be required: include `ambience` default `"none"` and `sfx` default `[]` in schema as required fields).

- [ ] **Step 2: Update schema + prompts**

In prompts: instruct model to choose ambience from the enum and 0–2 sfx cues that match the narration (not random).

In generator parse path: after building each `SceneData`, run `apply_sfx_fallback`.

- [ ] **Step 3: Run related tests**

Run: `pytest tests/test_script_schema.py tests/test_models.py tests/test_sfx_tags.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/youtube_pipeline/script_engine tests/
git commit -m "feat: request ambience/sfx tags from script engine"
```

---

### Task 4: FFmpeg mix — ambience timeline + one-shots

**Files:**
- Modify: `src/youtube_pipeline/video/ffmpeg_composer.py`
- Optionally create: `src/youtube_pipeline/video/sfx_mix.py` for filter-graph builder (preferred if `_mux_audio` grows)
- Test: `tests/test_sfx_mux.py`

**Interfaces:**
- Consumes: `VideoScript.scenes[].ambience/sfx/duration`, pack resolvers, scene_durations list
- Produces:

```python
def build_sfx_filter_complex(
    *,
    scene_durations: list[float],
    scenes: list[SceneData],
    has_bgm: bool,
    ambience_inputs: list[tuple[int, Path]],  # ffmpeg input index, path
    oneshot_inputs: list[tuple[int, Path, float]],  # index, path, delay_ms
) -> str:
    """Return filter_complex string ending with [a] mixed bus."""
```

Extend `_mux_audio` signature:

```python
def _mux_audio(
    self,
    video: Path,
    voiceover: Path,
    dest: Path,
    *,
    bgm_path: Path | None,
    script: VideoScript | None = None,
    scene_durations: list[float] | None = None,
) -> None:
```

When `script` provided, collect existing pack files for scenes, add as extra `-i` inputs, build filter; else keep legacy VO±BGM path.

- [ ] **Step 1: Unit-test filter builder (no ffmpeg)**

```python
def test_build_sfx_filter_includes_adelay_and_amix():
    # Construct fake SceneData list with rain + thunder at 0.4
    # durations [5.0, 5.0]
    # Assert "aloop" or amix inputs count, "adelay", volume=0.12, [a] label present
```

- [ ] **Step 2: Implement builder + wire compose()**

Pass `script` and `scene_durations` into `_mux_audio` from `compose()`.

Ambience scheduling: for scene i starting at `t0 = sum(durations[:i])`, duration `d`, use `aloop` + `atrim=0:d` + `adelay=t0_ms` + fade.

One-shots: `adelay=(t0 + at*d)*1000` ms.

Mix order: `[vo][bg?][amb_bus][shot_bus]amix=...`

If no ambience and no oneshots resolve, use existing VO±BGM code path.

- [ ] **Step 3: Optional integration** — if ffmpeg available, compose 2-scene fixture with pack rain; assert output mp3/aac stream exists (skip if no ffmpeg).

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_sfx_mux.py tests/test_hitl_zip_and_ffmpeg.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/youtube_pipeline/video tests/test_sfx_mux.py
git commit -m "feat: mix scene ambience and oneshots in FFmpeg assemble"
```

---

### Task 5: Workspace + API ambience override

**Files:**
- Modify: `src/youtube_pipeline/assets/hitl_workspace.py` (`workspace_status` scene dicts)
- Modify: `src/youtube_pipeline/api/schemas.py` (`SceneSlot.ambience`, `SceneSlot.sfx`)
- Modify: `src/youtube_pipeline/api/main.py` — `POST /api/v1/jobs/{job_id}/scenes/{scene_id}/ambience`
- Test: extend `tests/test_hitl_workspace.py` or `tests/test_sfx_tags.py`

**Interfaces:**
- Produces:

```http
POST /api/v1/jobs/{job_id}/scenes/{scene_id}/ambience
Content-Type: application/json
{"ambience": "rain"}
```

Persist by updating `script.json` (and timed script if present) scene entry; re-publish static.

`SceneSlot` gains:

```python
ambience: str = "none"
sfx: list[dict[str, Any]] = Field(default_factory=list)
```

- [ ] **Step 1: Failing API test** — set ambience, reload workspace, assert value.

- [ ] **Step 2: Implement persist helper + endpoint**

```python
def set_scene_ambience(run_dir: Path | str, scene_id: int, ambience: str) -> str:
    """Normalize and write ambience into script.json scenes; return stored value."""
```

- [ ] **Step 3: Tests pass + commit**

```bash
git commit -m "feat: expose and override scene ambience in studio API"
```

---

### Task 6: Frontend — show tags + ambience dropdown

**Files:**
- Modify: `frontend/src/api/types.ts`, `client.ts`
- Modify: `frontend/src/components/JobStudio.tsx`
- Build: `npm run build`

**Interfaces:**
- Consumes: workspace `ambience`/`sfx`; `updateSceneAmbience(jobId, sceneId, ambience)`

- [ ] **Step 1: Client helper**

```typescript
export async function updateSceneAmbience(jobId: string, sceneId: number, ambience: string) {
  const res = await fetch(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/scenes/${encodeURIComponent(sceneId)}/ambience`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ambience }),
    },
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}
```

- [ ] **Step 2: Scene card UI**

Show `Ambience: {tag}` and `SFX: thunder@0.4` text. If `canEdit`, `<select>` with enum options calling `updateSceneAmbience` then `loadWs`.

- [ ] **Step 3: Build**

Run: `cd frontend && npm run build`

- [ ] **Step 4: Commit**

```bash
git add frontend/src web/
git commit -m "feat: studio ambience picker and sfx tags display"
```

---

### Task 7: Verification

- [ ] **Step 1:** `pytest -q` (ignore known pre-existing Windows Telugu/Celery failures)
- [ ] **Step 2:** `cd frontend && npm run lint`
- [ ] **Step 3:** Manual smoke — short job with rain narration → Assemble → hear soft rain under VO
- [ ] **Step 4:** Push branch

---

## Spec coverage

| Spec item | Task |
|-----------|------|
| Bundled pack + LICENSE | Task 1 |
| Schema ambience/sfx | Tasks 2–3 |
| Keyword fallback | Task 2 |
| LLM tags | Task 3 |
| FFmpeg mix + volumes | Task 4 |
| Soft-fail missing files | Task 4 |
| Studio override | Tasks 5–6 |
| Tests | Tasks 2, 4, 5, 7 |

## Self-review notes

- No TBD placeholders; pack generation uses ffmpeg so CI/dev work offline.
- Volumes and tag enums match the approved spec exactly.
- Legacy assemble path preserved when no SFX resolves.
