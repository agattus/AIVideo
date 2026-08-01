# Gemini Image Auto-Fill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-fill scene stills with Gemini when Phase 1 hits `waiting_for_assets`, while keeping Flow/upload/regenerate overrides in Studio.

**Architecture:** Add `GeminiImageProvider` (`fetch_for_scene`), wire it through `build_asset_provider`, run `auto_fill_scene_images` at the end of Phase 1 (skip when `ASSET_PROVIDER=manual`), expose regenerate API endpoints, and update `JobStudio` for hybrid UX. Reuse `save_scene_image` + `publish_workspace_static` so Assemble stays unchanged.

**Tech Stack:** Python 3.12, FastAPI, `google-generativeai` (already in requirements), Pillow, React/Vite studio, pytest + FastAPI TestClient.

## Global Constraints

- Do not auto-assemble; status stays `waiting_for_assets` after auto-fill.
- Soft-fail: missing key / per-scene errors must not wipe script/audio.
- No live Google API calls in CI — mock Gemini responses.
- Reuse workspace paths `assets/scene_XX.jpg` via `save_scene_image`.
- Product default documented as `ASSET_PROVIDER=gemini_image`; `imagen` aliases to the same provider; `manual` skips auto-fill.
- Default image model: `GEMINI_IMAGE_MODEL=gemini-2.5-flash-image`.
- Flow override URL: `https://labs.google/fx/tools/flow`.
- Sequential generation for v1 (no concurrency pool).
- `SceneSlot` / `WorkspaceResponse` use `extra="forbid"` — new fields must be added to the Pydantic models explicitly.

## File Structure

| File | Responsibility |
|------|----------------|
| `config/settings.py` | `AssetProvider.GEMINI_IMAGE`, `gemini_image_model`, coerce `imagen` → gemini_image |
| `src/youtube_pipeline/assets/gemini_image.py` | Gemini `generate_content` → image bytes → `MediaAsset` |
| `src/youtube_pipeline/assets/factory.py` | Build gemini_image / imagen provider |
| `src/youtube_pipeline/assets/hitl_workspace.py` | `auto_fill_scene_images`, optional scene `source`/`error` in workspace |
| `src/youtube_pipeline/api/tasks.py` | Call auto-fill after Phase 1 publish; progress updates |
| `src/youtube_pipeline/api/schemas.py` | SceneSlot optional fields; generate response models |
| `src/youtube_pipeline/api/main.py` | `POST .../generate-images`, `POST .../scenes/{id}/generate` |
| `frontend/src/api/types.ts`, `client.ts` | Types + API helpers |
| `frontend/src/components/JobStudio.tsx` | Hybrid UI actions + copy |
| `.env.example`, `render.yaml` | Document / set `ASSET_PROVIDER=gemini_image` |
| `tests/test_gemini_image_provider.py` | Provider unit tests (mocked) |
| `tests/test_auto_fill_images.py` | Auto-fill + API tests (mocked provider) |

---

### Task 1: Settings — `gemini_image` provider + model

**Files:**
- Modify: `config/settings.py`
- Modify: `.env.example`
- Test: `tests/test_settings_secrets.py` (extend) or `tests/test_models.py` if settings coercion lives there

**Interfaces:**
- Produces: `AssetProvider.GEMINI_IMAGE = "gemini_image"`; `Settings.gemini_image_model: str = "gemini-2.5-flash-image"`; validator maps `imagen` → `gemini_image`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_settings_secrets.py` (or new `tests/test_asset_provider_settings.py`):

```python
import os
from unittest.mock import patch

from config.settings import AssetProvider, Settings


def test_imagen_coerces_to_gemini_image():
    with patch.dict(os.environ, {"ASSET_PROVIDER": "imagen"}, clear=False):
        s = Settings(_env_file=None)
        assert s.asset_provider == AssetProvider.GEMINI_IMAGE


def test_gemini_image_model_default():
    with patch.dict(os.environ, {"ASSET_PROVIDER": "gemini_image"}, clear=False):
        s = Settings(_env_file=None)
        assert s.gemini_image_model == "gemini-2.5-flash-image"
```

Adjust if `Settings` construction in this repo always reads `.env` — follow patterns in `tests/test_settings_secrets.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_settings_secrets.py -k "imagen_coerces or gemini_image_model" -v`  
Expected: FAIL (enum member / field missing)

- [ ] **Step 3: Minimal settings implementation**

In `config/settings.py`:

```python
class AssetProvider(str, Enum):
    POLLINATIONS = "pollinations"
    OPENAI_IMAGE = "openai_image"
    IMAGEN = "imagen"          # keep for env compatibility; coerced to gemini_image
    GEMINI_IMAGE = "gemini_image"
    MANUAL = "manual"
```

Add field:

```python
gemini_image_model: str = "gemini-2.5-flash-image"
```

In `_coerce_legacy_asset_provider`, after legacy stock mapping:

```python
if text == "imagen":
    return AssetProvider.GEMINI_IMAGE
```

Update `.env.example`:

```env
# Asset providers:
#   gemini_image  -> Gemini native image (default product path; needs GEMINI_API_KEY)
#   pollinations  -> free pollinations.ai images (no key)
#   openai_image  -> OpenAI DALL-E 3 (OPENAI_API_KEY)
#   imagen        -> alias for gemini_image
#   manual        -> skip auto image gen (Flow / upload only)
ASSET_PROVIDER=gemini_image
GEMINI_IMAGE_MODEL=gemini-2.5-flash-image
```

Do **not** change the Python default of `asset_provider` away from `POLLINATIONS` unless tests expect it — documented default for new deploys is via `.env.example` / Render only (per spec).

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_settings_secrets.py tests/test_tts_provider_enum.py -v`  
Expected: PASS (and any AssetProvider enum tests updated if they enumerate members)

- [ ] **Step 5: Commit**

```bash
git add config/settings.py .env.example tests/
git commit -m "feat: add gemini_image asset provider settings"
```

---

### Task 2: `GeminiImageProvider`

**Files:**
- Create: `src/youtube_pipeline/assets/gemini_image.py`
- Modify: `src/youtube_pipeline/assets/factory.py`
- Modify: `src/youtube_pipeline/assets/__init__.py` (only if other providers are exported)
- Test: `tests/test_gemini_image_provider.py`

**Interfaces:**
- Consumes: `Settings.gemini_api_key`, `Settings.gemini_image_model`; `SceneData`, `AssetProviderProtocol`
- Produces: `class GeminiImageProvider` with `name = "gemini_image"` and `def fetch_for_scene(self, scene: SceneData, output_dir: Path) -> MediaAsset`

- [ ] **Step 1: Write the failing test**

Create `tests/test_gemini_image_provider.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from youtube_pipeline.exceptions import ConfigurationError
from youtube_pipeline.models import SceneData


def _tiny_png_bytes() -> bytes:
    # 1x1 PNG
    import base64
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


def test_fetch_for_scene_writes_image(tmp_path: Path):
    from youtube_pipeline.assets.gemini_image import GeminiImageProvider

    settings = Settings(
        _env_file=None,
        gemini_api_key="test-key",
        gemini_image_model="gemini-2.5-flash-image",
        asset_provider="gemini_image",
    )
    provider = GeminiImageProvider(settings)
    scene = SceneData(
        scene_id=0,
        script_text="Hello",
        visual_prompt="Cinematic mountain at dawn",
    )

    part = MagicMock()
    part.inline_data = MagicMock()
    part.inline_data.mime_type = "image/png"
    part.inline_data.data = _tiny_png_bytes()
    response = MagicMock()
    response.parts = [part]
    response.candidates = [MagicMock()]

    with patch("youtube_pipeline.assets.gemini_image.genai") as genai:
        model = MagicMock()
        model.generate_content.return_value = response
        genai.GenerativeModel.return_value = model
        asset = provider.fetch_for_scene(scene, tmp_path)

    assert asset.scene_id == 0
    assert asset.source == "gemini_image"
    assert asset.media_type == "image"
    assert Path(asset.path).exists()
    assert Path(asset.path).stat().st_size > 10


def test_missing_api_key_raises():
    from youtube_pipeline.assets.gemini_image import GeminiImageProvider

    settings = Settings(_env_file=None, gemini_api_key=None, asset_provider="gemini_image")
    with pytest.raises(ConfigurationError):
        GeminiImageProvider(settings)


def test_factory_builds_gemini_image():
    from youtube_pipeline.assets.factory import build_asset_provider

    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        asset_provider="gemini_image",
    )
    provider = build_asset_provider(settings)
    assert provider.name == "gemini_image"
```

If `Settings(...)` kwargs differ in this codebase, construct via env patch like other tests.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gemini_image_provider.py -v`  
Expected: FAIL import / not implemented

- [ ] **Step 3: Implement provider + factory**

`src/youtube_pipeline/assets/gemini_image.py`:

```python
"""Gemini native image generation (Nano Banana / flash-image models)."""

from __future__ import annotations

from pathlib import Path

import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import Settings, get_settings
from youtube_pipeline.exceptions import AssetAcquisitionError, ConfigurationError
from youtube_pipeline.models import MediaAsset, SceneData
from youtube_pipeline.utils.files import ensure_dir, slugify
from youtube_pipeline.utils.logging import get_logger

logger = get_logger(__name__)


class GeminiImageProvider:
    name = "gemini_image"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.gemini_api_key:
            raise ConfigurationError(
                "GEMINI_API_KEY is required for asset provider 'gemini_image'"
            )
        genai.configure(api_key=self.settings.gemini_api_key)

    def fetch_for_scene(self, scene: SceneData, output_dir: Path) -> MediaAsset:
        logger.info("Gemini image gen | scene=%d", scene.scene_id)
        try:
            image_bytes = self._generate(scene.visual_prompt)
        except Exception as exc:  # noqa: BLE001
            raise AssetAcquisitionError(f"Gemini image generation failed: {exc}") from exc

        dest = ensure_dir(output_dir) / (
            f"scene_{scene.scene_id:02d}_{slugify(scene.visual_prompt)[:40]}.png"
        )
        dest.write_bytes(image_bytes)
        return MediaAsset(
            scene_id=scene.scene_id,
            path=str(dest),
            source=self.name,
            media_type="image",
            attribution="AI-generated via Gemini",
        )

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def _generate(self, prompt: str) -> bytes:
        model = genai.GenerativeModel(self.settings.gemini_image_model)
        response = model.generate_content(prompt)
        return _extract_image_bytes(response)


def _extract_image_bytes(response: object) -> bytes:
    parts = getattr(response, "parts", None) or []
    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline is None:
            continue
        data = getattr(inline, "data", None)
        if data:
            return bytes(data) if not isinstance(data, bytes) else data
    raise AssetAcquisitionError("Gemini response contained no image data")
```

In `factory.py`:

```python
from youtube_pipeline.assets.gemini_image import GeminiImageProvider

# ...
if settings.asset_provider in {AssetProvider.GEMINI_IMAGE, AssetProvider.IMAGEN}:
    return GeminiImageProvider(settings)
# remove the old IMAGEN ConfigurationError raise
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_gemini_image_provider.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/youtube_pipeline/assets/gemini_image.py src/youtube_pipeline/assets/factory.py tests/test_gemini_image_provider.py
git commit -m "feat: add GeminiImageProvider for scene stills"
```

---

### Task 3: `auto_fill_scene_images` in HITL workspace

**Files:**
- Modify: `src/youtube_pipeline/assets/hitl_workspace.py`
- Modify: `src/youtube_pipeline/api/schemas.py` (`SceneSlot.source`, `SceneSlot.error` optional)
- Test: `tests/test_auto_fill_images.py`

**Interfaces:**
- Consumes: `save_scene_image`, `build_asset_provider`, `load_prompts` / prompts.json, `SceneData`
- Produces:

```python
def auto_fill_scene_images(
    run_dir: Path | str,
    *,
    force: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Fill missing scene images via configured asset provider.

    Returns {"filled": int, "skipped": int, "failed": list[dict], "provider": str}
    """
```

Also: persist per-scene errors under `run_dir / "assets" / "scene_errors.json"` (map `str(scene_id)` → message) so workspace can surface them; clear error for a scene on successful save.

`workspace_status` adds optional keys on each scene: `source` (`"gemini"|"upload"|""`), `error` (str).

`SceneSlot` gains:

```python
source: Optional[str] = None
error: Optional[str] = None
```

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auto_fill_images.py
from pathlib import Path
from unittest.mock import MagicMock, patch

from youtube_pipeline.assets.hitl_workspace import auto_fill_scene_images, save_scene_image, workspace_status
from youtube_pipeline.models import MediaAsset
# reuse _make_run from test_hitl_workspace or duplicate helper


def test_auto_fill_writes_missing_scenes(tmp_path: Path):
    from tests.test_hitl_workspace import _make_run  # or inline helper

    run = _make_run(tmp_path, scenes=2)
    fake_bytes = Path(__file__).parent  # use PIL tiny jpeg like other tests

    def fake_fetch(scene, output_dir):
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), color=(10, 20, 30)).save(buf, format="JPEG")
        dest = Path(output_dir) / f"raw_{scene.scene_id}.jpg"
        dest.write_bytes(buf.getvalue())
        return MediaAsset(
            scene_id=scene.scene_id,
            path=str(dest),
            source="gemini_image",
            media_type="image",
        )

    provider = MagicMock()
    provider.name = "gemini_image"
    provider.fetch_for_scene.side_effect = fake_fetch

    with patch(
        "youtube_pipeline.assets.hitl_workspace.build_asset_provider",
        return_value=provider,
    ):
        result = auto_fill_scene_images(run)

    assert result["filled"] == 2
    assert (run / "assets" / "scene_00.jpg").exists()
    assert (run / "assets" / "scene_01.jpg").exists()


def test_auto_fill_skips_ready_unless_force(tmp_path: Path):
    # save one scene first, mock provider, assert only missing filled unless force=True
    ...


def test_auto_fill_continues_after_scene_failure(tmp_path: Path):
    # first scene raises, second succeeds → failed list length 1, filled 1
    ...
```

Use the same PIL JPEG helper pattern as `tests/test_hitl_workspace.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auto_fill_images.py -v`  
Expected: FAIL (`auto_fill_scene_images` missing)

- [ ] **Step 3: Implement auto-fill**

In `hitl_workspace.py`:

```python
def auto_fill_scene_images(
    run_dir: Path | str,
    *,
    force: bool = False,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    from config.settings import AssetProvider, get_settings
    from youtube_pipeline.assets.factory import build_asset_provider
    from youtube_pipeline.models import SceneData

    root = Path(run_dir)
    settings = get_settings()
    if settings.asset_provider == AssetProvider.MANUAL:
        return {"filled": 0, "skipped": 0, "failed": [], "provider": "manual", "skipped_manual": True}

    provider = build_asset_provider(settings)
    payload = load_prompts(root)
    scenes = payload.get("scenes") or []
    total = len(scenes)
    filled = 0
    skipped = 0
    failed: list[dict[str, Any]] = []
    errors = _load_scene_errors(root)

    tmp_dir = ensure_dir(root / "assets" / "_gen")
    for index, scene in enumerate(scenes):
        sid = int(scene["scene_id"])
        dest = scene_image_path(root, sid)
        if dest.exists() and dest.stat().st_size > 256 and not force:
            skipped += 1
            continue
        if on_progress:
            on_progress(index + 1, total, f"Generating scene {index + 1}/{total}")
        try:
            scene_data = SceneData(
                scene_id=sid,
                script_text=str(scene.get("script_text") or f"Scene {sid}"),
                visual_prompt=str(scene.get("visual_prompt") or ""),
            )
            if not scene_data.visual_prompt.strip():
                raise ValueError("Empty visual_prompt")
            asset = provider.fetch_for_scene(scene_data, tmp_dir)
            data = Path(asset.path).read_bytes()
            save_scene_image(root, sid, data, source_name=Path(asset.path).name)
            _remember_scene_source(root, sid, provider.name)
            errors.pop(str(sid), None)
            filled += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Scene image auto-fill failed | scene=%s | %s", sid, exc)
            failed.append({"scene_id": sid, "error": str(exc)})
            errors[str(sid)] = str(exc)

    _save_scene_errors(root, errors)
    return {
        "filled": filled,
        "skipped": skipped,
        "failed": failed,
        "provider": provider.name,
    }
```

Helpers `_load_scene_errors` / `_save_scene_errors` / `_remember_scene_source` write small JSON sidecars under `assets/`. In `workspace_status` scene dicts, set `error` from that map and `source` from sidecar when present.

Update `SceneSlot` in schemas with optional `source` and `error`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_auto_fill_images.py tests/test_hitl_workspace.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/youtube_pipeline/assets/hitl_workspace.py src/youtube_pipeline/api/schemas.py tests/test_auto_fill_images.py
git commit -m "feat: auto-fill scene images via asset provider"
```

---

### Task 4: Hook auto-fill into Phase 1 (`execute_video_pipeline`)

**Files:**
- Modify: `src/youtube_pipeline/api/tasks.py`
- Test: `tests/test_auto_fill_images.py` (add test with patched orchestrator) or `tests/test_orchestrator.py` / `tests/test_api.py`

**Interfaces:**
- Consumes: `auto_fill_scene_images(run_dir, on_progress=...)`, `publish_workspace_static`, `update_job`
- Produces: After setting `WAITING_FOR_ASSETS` artifacts, call auto-fill before returning; keep status `waiting_for_assets`; update `current_stage` during fill then to a review message

- [ ] **Step 1: Write the failing test**

Prefer a focused unit test that patches `VideoPipelineOrchestrator.run` and asserts `auto_fill_scene_images` is called:

```python
def test_execute_video_pipeline_calls_auto_fill(tmp_path, monkeypatch):
    # init job, fake orchestrator result with run_dir containing prompts+audio,
    # patch auto_fill_scene_images, call execute_video_pipeline, assert called once
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auto_fill_images.py::test_execute_video_pipeline_calls_auto_fill -v`  
Expected: FAIL (not called)

- [ ] **Step 3: Wire into `execute_video_pipeline`**

In `tasks.py`, after `publish_workspace_static` and before/after the first `WAITING_FOR_ASSETS` update:

```python
from config.settings import AssetProvider, get_settings
from youtube_pipeline.assets.hitl_workspace import auto_fill_scene_images, publish_workspace_static

# after publish_workspace_static(...)
settings = get_settings()
if settings.asset_provider != AssetProvider.MANUAL:
    def _img_progress(done: int, total: int, label: str) -> None:
        # Map into ~75-90% band
        pct = 75 + int(15 * (done / max(total, 1)))
        update_job(
            job_id,
            status=JobStatus.WAITING_FOR_ASSETS,
            current_stage=label,
            progress_percent=min(pct, 90),
            run_dir=str(run_dir.resolve()),
        )

    fill = auto_fill_scene_images(run_dir, on_progress=_img_progress)
    publish_workspace_static(job_id, run_dir, STATIC_DIR)
    stage = "Review scene images, then assemble"
    if fill.get("failed"):
        stage = f"Some images failed ({len(fill['failed'])}) — regenerate or upload"
else:
    stage = "Your turn — add scene images, then assemble"

update_job(
    job_id,
    status=JobStatus.WAITING_FOR_ASSETS,
    current_stage=stage,
    progress_percent=75 if settings.asset_provider == AssetProvider.MANUAL else 92,
    ...
)
```

Catch top-level auto-fill crashes so Phase 1 still ends in `waiting_for_assets` with an error note rather than `failed` (script/audio already done).

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_auto_fill_images.py tests/test_api.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/youtube_pipeline/api/tasks.py tests/test_auto_fill_images.py
git commit -m "feat: auto-fill scene images after Phase 1"
```

---

### Task 5: Regenerate API endpoints

**Files:**
- Modify: `src/youtube_pipeline/api/main.py`
- Modify: `src/youtube_pipeline/api/schemas.py` (request/response models)
- Test: `tests/test_auto_fill_images.py` or extend `tests/test_hitl_workspace.py` / `tests/test_api.py`

**Interfaces:**
- Produces:

```http
POST /api/v1/jobs/{job_id}/scenes/{scene_id}/generate
POST /api/v1/jobs/{job_id}/generate-images?force=false
```

Response body example:

```json
{"job_id": "...", "filled": 1, "skipped": 0, "failed": [], "provider": "gemini_image"}
```

- [ ] **Step 1: Write the failing API tests**

```python
def test_generate_one_scene_endpoint(tmp_path):
    # init_job WAITING_FOR_ASSETS with run_dir=_make_run
    # patch build_asset_provider / auto_fill or provider.fetch_for_scene
    # client.post(f"/api/v1/jobs/{job_id}/scenes/0/generate")
    # assert 200 and scene_00.jpg exists


def test_generate_images_fills_missing(tmp_path):
    # POST /api/v1/jobs/{job_id}/generate-images
    ...
```

Follow TestClient + `_FakeRedis` pattern from `tests/test_hitl_workspace.py`.

- [ ] **Step 2: Run tests — expect FAIL (404)**

Run: `pytest tests/test_auto_fill_images.py -k generate -v`

- [ ] **Step 3: Implement endpoints**

Add schemas:

```python
class GenerateImagesAccepted(BaseModel):
    job_id: str
    filled: int = 0
    skipped: int = 0
    failed: list[dict[str, Any]] = Field(default_factory=list)
    provider: str = ""
    message: str = ""
```

In `main.py`, resolve `run_dir` from job like other HITL routes; reject if job missing / no `run_dir`; for single-scene generate, either call a thin `generate_one_scene_image(run_dir, scene_id)` helper or `auto_fill` with a filter — prefer a small helper in `hitl_workspace.py`:

```python
def generate_one_scene_image(run_dir: Path | str, scene_id: int) -> dict[str, Any]:
    """Force-generate a single scene; returns same shape keys as auto_fill for one id."""
```

After generate, call `publish_workspace_static(job_id, run_dir, STATIC_DIR)`.

If `ASSET_PROVIDER=manual`, return HTTP 400 with clear message to upload or switch provider.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_auto_fill_images.py tests/test_hitl_workspace.py tests/test_api.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/youtube_pipeline/api/main.py src/youtube_pipeline/api/schemas.py src/youtube_pipeline/assets/hitl_workspace.py tests/
git commit -m "feat: API endpoints to regenerate scene images"
```

---

### Task 6: Frontend hybrid Studio UX

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/components/JobStudio.tsx`
- Modify: `frontend/src/lib/progressCopy.ts` (only if stage strings need friendly mapping)
- Build: `npm run build` (writes `web/`)

**Interfaces:**
- Consumes: new API routes
- Produces: UI actions Regenerat / Copy / Open Flow / Upload; updated helper copy

- [ ] **Step 1: Extend client + types**

```typescript
// types.ts — SceneSlot
source?: string | null;
error?: string | null;

// client.ts
export async function generateSceneImage(jobId: string, sceneId: number) {
  const res = await fetch(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/scenes/${encodeURIComponent(sceneId)}/generate`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateMissingImages(jobId: string, force = false) {
  const q = force ? "?force=true" : "";
  const res = await fetch(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/generate-images${q}`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
```

- [ ] **Step 2: Update JobStudio copy + actions**

- Replace “Meta AI / Gemini” copy with hybrid wording: images generate automatically; use Flow if you want a different look.
- Toolbar: **Regenerate missing** button calling `generateMissingImages(jobId)`.
- Per scene: **Regenerate** → `generateSceneImage`; **Copy prompt**; **Open Flow** → `navigator.clipboard.writeText(prompt)` then `window.open("https://labs.google/fx/tools/flow", "_blank", "noopener,noreferrer")`; keep upload.
- Show `scene.error` under the card when present.
- Disable regenerate buttons while a generate request is in flight; refresh workspace after success.

- [ ] **Step 3: Build frontend**

Run: `cd frontend && npm run build`  
Expected: success; `web/` updated

- [ ] **Step 4: Manual smoke (local)**

With `ASSET_PROVIDER=manual`, UI still allows upload/Flow.  
With mocked backend or live key locally, regenerate buttons hit the new routes (optional if no key).

- [ ] **Step 5: Commit**

```bash
git add frontend/src web/
git commit -m "feat: hybrid Studio actions for Gemini images and Flow"
```

---

### Task 7: Deploy config + README note

**Files:**
- Modify: `render.yaml` — set `ASSET_PROVIDER=gemini_image`, add `GEMINI_IMAGE_MODEL`
- Modify: `README.md` — short note under studio / deploy that scene images auto-fill via Gemini

- [ ] **Step 1: Update render.yaml envVars**

```yaml
- key: ASSET_PROVIDER
  value: gemini_image
- key: GEMINI_IMAGE_MODEL
  value: gemini-2.5-flash-image
```

Keep `GEMINI_API_KEY` as `sync: false`.

- [ ] **Step 2: README blurb**

Add 3–5 lines under the studio section: Phase 1 auto-fills stills with Gemini; override per scene with Flow/upload; `ASSET_PROVIDER=manual` disables auto-fill.

- [ ] **Step 3: Commit**

```bash
git add render.yaml README.md
git commit -m "docs: enable gemini_image on Render and document hybrid flow"
```

---

### Task 8: Full verification

- [ ] **Step 1: Run full test suite**

Run: `pytest -q`  
Expected: all PASS

- [ ] **Step 2: Lint frontend**

Run: `cd frontend && npm run lint`  
Expected: clean (or only pre-existing issues)

- [ ] **Step 3: Push and redeploy**

Push `main`; Render auto-deploys. Confirm dashboard has `GEMINI_API_KEY` and `ASSET_PROVIDER=gemini_image`.

- [ ] **Step 4: Live smoke on Render**

Open `https://aivideo-w061.onrender.com/`, generate a short 2–3 scene idea, wait for scene previews without leaving the app, replace one via upload if desired, Assemble.

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| GeminiImageProvider | Task 2 |
| Settings gemini_image + imagen alias + model | Task 1 |
| Auto-fill after Phase 1 | Tasks 3–4 |
| Status stays waiting_for_assets | Task 4 |
| Soft-fail / per-scene errors | Tasks 3–4 |
| Regenerate one / fill missing APIs | Task 5 |
| Studio hybrid UI + Flow link | Task 6 |
| manual skips auto-fill | Tasks 3–4 |
| .env.example + Render | Tasks 1, 7 |
| Mocked tests, no live Google in CI | Tasks 2–5, 8 |

## Self-review notes

- No TBD/placeholder steps; Flow URL fixed to `https://labs.google/fx/tools/flow`.
- Sequential fill only (spec v1).
- `SceneSlot` optional fields added explicitly for `extra="forbid"`.
- Python default `asset_provider` left as Pollinations unless deploy/env sets gemini_image — matches “documented default” without surprising existing local envs.
