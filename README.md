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

### Folder structure

```text
.
├── cli.py                          # Typer CLI entrypoint
├── config/
│   └── settings.py                 # Env-backed settings (pydantic-settings)
├── src/youtube_pipeline/
│   ├── models.py                   # Shared domain models
│   ├── orchestrator.py             # Core end-to-end orchestration
│   ├── exceptions.py
│   ├── script_engine/              # LLM script + visual prompt generation
│   ├── audio/                      # TTS + subtitle writers
│   ├── assets/                     # Stock + AI image providers
│   ├── video/                      # MoviePy composer, Ken Burns, captions
│   └── utils/
├── tests/
├── requirements.txt
├── pyproject.toml
└── .env.example
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Fill in at least:
#   OPENAI_API_KEY
#   PEXELS_API_KEY   (or PIXABAY_API_KEY / use openai_image)

python cli.py generate \
  "How black holes warp spacetime" \
  --style cinematic \
  --duration 45 \
  --max-scenes 6
```

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
| `LLM_PROVIDER` | `openai` or `anthropic` |
| `TTS_PROVIDER` | `openai`, `elevenlabs`, or `gtts` |
| `ASSET_PROVIDER` | `pexels`, `pixabay`, or `openai_image` |
| `VIDEO_WIDTH` / `VIDEO_HEIGHT` / `VIDEO_FPS` | Output defaults (16:9) |

## Core modules

### Orchestrator (`orchestrator.py`)

`VideoPipelineOrchestrator.run(PipelineRequest)` wires every stage, writes intermediate JSON artifacts into a timestamped run directory under `output/`, and returns a `PipelineResult`.

Stages are injectable (script/audio/assets/composer) for testing and swapping providers.

### Video composer (`video/composer.py`)

- Sequences scene assets to audio-aligned timestamps
- Applies Ken Burns pan/zoom on stills (`video/ken_burns.py`)
- Burns stylized captions (`video/captions.py`)
- Overlays the TTS track and renders H.264/AAC via MoviePy/FFmpeg

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
