# YouTube Video Automation Pipeline

Modular, production-oriented Python system that turns an **idea + visual style** into a complete narrated YouTube video:

**Idea / Style → Script + Visual Prompts → TTS + Subtitles → Assets → MoviePy Compose → `.mp4`**

## Architecture

```text
PipelineRequest(idea, style)
        |
        v
  ScriptEngine        LLM (Groq llama-3.3-70b / OpenAI / Anthropic)
                      -> full voiceover + per-scene visual prompts
        |
        v
  AudioEngine         TTS (OpenAI / ElevenLabs)
  + SubtitleWriter    -> voiceover.mp3 + .srt / .vtt
        |
        v
  AssetService        Pexels Video → Pexels Image → DALL-E 3
                      -> scene_XX.mp4 / scene_XX.png
        |
        v
  timing.align...     Map scenes onto audio duration
        |
        v
  VideoComposer       MoviePy: Ken Burns + captions + audio mux
        |
        v
  PipelineResult (.mp4 + sidecars)
```

### Async mobile API + Web studio

Open the UI at **http://localhost:8000/** after starting the API.

```text
POST /api/v1/generate  -> 202 { job_id, status: queued }
GET  /api/v1/status/{job_id}  -> progress + download_urls
GET  /static/{job_id}/video.mp4
```

**Easiest (Docker):**

```bash
docker compose up --build
# open http://localhost:8000
```

**Local without Docker (in-process worker fallback):**

```bash
# from the repo root
pip install -r requirements.txt
pip install -e .                 # important: installs both youtube_pipeline and config

cp .env.example .env   # set GROQ_API_KEY, GEMINI_API_KEY, TTS_PROVIDER=edge-tts, ASSET_PROVIDER=imagen

# Windows PowerShell:
$env:PYTHONPATH = "src;."
uvicorn src.youtube_pipeline.api.main:app --reload --port 8000

# macOS / Linux:
PYTHONPATH=src:. uvicorn src.youtube_pipeline.api.main:app --reload --port 8000

# open http://localhost:8000
```

If Redis is unavailable, jobs still run in a background thread so the UI keeps working.
On Windows, prefer ``pip install -e .`` so ``config.settings`` imports succeed inside worker threads.

### Folder structure

```text
.
├── cli.py                          # Typer CLI entrypoint
├── Dockerfile / docker-compose.yml # API + Celery + Redis
├── config/
│   └── settings.py                 # Env-backed settings (pydantic-settings)
├── src/youtube_pipeline/
│   ├── models.py                   # Shared domain models
│   ├── orchestrator.py             # Core end-to-end orchestration
│   ├── api/                        # FastAPI + Celery microservice layer
│   ├── exceptions.py
│   ├── script_engine/              # LLM script + visual prompt generation
│   ├── audio/                      # TTS + subtitle writers
│   ├── assets/                     # Generative image providers (Imagen / Pollinations)
│   ├── video/                      # MoviePy composer, Ken Burns, captions
│   └── utils/
├── tests/
├── requirements.txt
├── pyproject.toml
└── .env.example
```

## Quick start

```bash
git pull origin main
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# optional but recommended:
pip install -e .

cp .env.example .env
# Edit .env — recommended high-quality stack:
#   GROQ_API_KEY=gsk_...
#   GEMINI_API_KEY=...
#   TTS_PROVIDER=edge-tts
#   ASSET_PROVIDER=imagen

python cli.py doctor
python cli.py generate \
  "How black holes warp spacetime" \
  --style cinematic \
  --duration 45 \
  --max-scenes 6
```

### Troubleshooting after merging `main`

| Symptom | Fix |
|---|---|
| `ASSET_PROVIDER` validation error (`pixabay` / `pexels`) | Set `ASSET_PROVIDER=imagen` or `pollinations` (legacy values remap to pollinations) |
| Missing `GEMINI_API_KEY` with `ASSET_PROVIDER=imagen` | Add a key from https://aistudio.google.com/apikey |
| `ModuleNotFoundError: dotenv` / `pydantic` / `fastapi` | Reinstall: `pip install -r requirements.txt` |
| `GROQ_API_KEY` / 401 errors | Put a fresh key in `.env` with **no quotes** |
| Redis connection errors for the API | Locally use `REDIS_URL=redis://localhost:6379/0`, or run `docker compose up` |
| Docker API can't find modules | Use compose as written (`PYTHONPATH=/app:/app/src`) |

List styles:

```bash
python cli.py styles
```

## Supported styles

| Style | Intent |
|---|---|
| `cinematic` | Dramatic lighting, shallow DOF, rich grading |
| `documentary` | Observational, natural light, informative pacing |
| `corporate` | Clean, brand-safe, professional polish |
| `fast_paced_shorts` | Punchy short-form energy (works with `9:16`) |
| `animated` | Illustration / stylized art direction |
| `minimal` | Calm negative space, restrained motion |

## Configuration

All settings load from environment / `.env` via `config.settings.Settings`.

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | `gemini` (default), `groq`, `openai`, or `anthropic` |
| `TTS_PROVIDER` | `openai`, `elevenlabs`, `gtts`, or `edge-tts` |
| `EDGE_TTS_VOICE` | Neural voice when using `edge-tts` (default `en-US-ChristopherNeural`) |
| `ASSET_PROVIDER` | `imagen` (default, Gemini image), `pollinations` (free), or `openai_image` |
| `GEMINI_API_KEY` | Required for Gemini scripts + image generation |
| `IMAGEN_MODEL` | Image model id (default `gemini-2.5-flash-image`) |
| `VIDEO_WIDTH` / `VIDEO_HEIGHT` / `VIDEO_FPS` | Output defaults (16:9) |
| `SCENE_CROSSFADE_SECONDS` | Dissolve overlap between scenes (default `0.45`) |
| `KEN_BURNS_ZOOM` | Still-image motion intensity (default `0.12`) |
| `BGM_VOLUME` / `BGM_FADE_SECONDS` | BGM ducking + fade sync under narration |
| `VOICEOVER_VOLUME` | Narration gain over BGM (default `1.05`) |

## Core modules

### Orchestrator (`orchestrator.py`)

`VideoPipelineOrchestrator.run(PipelineRequest)` wires every stage, writes intermediate JSON artifacts into a timestamped run directory under `output/`, and returns a `PipelineResult`.

Stages are injectable (script/audio/assets/composer) for testing and swapping providers.

### Video composer (`video/composer.py`)

- Sequences AI scene stills with cinematic crossfades
- Applies eased Ken Burns pan/zoom on stills (`video/ken_burns.py`)
- Burns dynamic Pillow captions with soft fades
- Syncs looped BGM under narration (fade-in/out + ducking) and renders H.264/AAC

## Programmatic usage

```python
from youtube_pipeline import (
    PipelineRequest,
    VideoPipelineOrchestrator,
    VisualStyle,
)

orch = VideoPipelineOrchestrator()
result = orch.run(
    PipelineRequest(
        idea="The science of deep sleep",
        style=VisualStyle.DOCUMENTARY,
        target_duration_seconds=60,
        max_scenes=6,
    )
)
print(result.video_path)
```

## Tests

```bash
pytest -q
```

Unit tests cover models, subtitle writing, scene-to-audio alignment, and orchestrator wiring with fakes (no API keys required).

## Extending

- **New LLM / TTS / asset backends**: implement the existing method contracts and register in the relevant factory (`assets/factory.py`) or settings enum.
- **Forced alignment**: replace `AudioEngine._estimate_word_timestamps` with provider word timings; subtitle + caption layers stay the same.
- **Runway / Midjourney / Leonardo**: add a provider class beside `OpenAIImageProvider` that returns a local `MediaAsset`.

## Notes

- MoviePy requires a working FFmpeg binary (`imageio-ffmpeg` ships one for most platforms).
- Caption burning needs a system font MoviePy/ImageMagick can resolve; DejaVu/Liberation paths are tried first.
- Stock providers currently fetch **images**; video stock/AI clips can plug into the same `MediaAsset` interface (`media_type="video"`).
