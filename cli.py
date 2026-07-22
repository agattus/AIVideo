#!/usr/bin/env python3
"""CLI entrypoint for the YouTube video automation pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root without an editable install.
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dotenv import load_dotenv

# Prefer the project .env over any empty/stale shell environment variables.
_ENV_FILE = ROOT / ".env"
load_dotenv(_ENV_FILE, override=True)
load_dotenv(override=False)

import typer
from rich.console import Console

from youtube_pipeline.models import AspectRatio, PipelineRequest, VisualStyle
from youtube_pipeline.utils.logging import get_logger, setup_logging

app = typer.Typer(
    add_completion=False,
    help="Generate a complete YouTube video from an idea and visual style.",
)
console = Console()
logger = get_logger("youtube_pipeline.cli")


@app.command("generate")
def generate(
    idea: str = typer.Argument(..., help="Core topic or video idea"),
    style: VisualStyle = typer.Option(
        VisualStyle.CINEMATIC,
        "--style",
        "-s",
        help="Visual style guiding script and asset prompts",
    ),
    aspect_ratio: AspectRatio = typer.Option(
        AspectRatio.LANDSCAPE,
        "--aspect-ratio",
        "-a",
        help="Output aspect ratio",
    ),
    duration: int = typer.Option(
        60,
        "--duration",
        "-d",
        min=15,
        max=3600,
        help="Target duration in seconds (script scales at ~140 WPM)",
    ),
    max_scenes: int = typer.Option(
        8,
        "--max-scenes",
        min=2,
        max=240,
        help="Max scenes (auto-raised to at least 1 scene per 15s of --duration)",
    ),
    voice: str | None = typer.Option(None, "--voice", help="Override TTS voice id/name"),
    output_name: str | None = typer.Option(None, "--name", help="Output basename"),
    no_captions: bool = typer.Option(False, "--no-captions", help="Disable burned-in captions"),
    no_ken_burns: bool = typer.Option(False, "--no-ken-burns", help="Disable Ken Burns motion"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable DEBUG logging"),
) -> None:
    """Run the full automation pipeline end-to-end.

    Example::

        python cli.py generate "How black holes warp spacetime" --style cinematic
    """
    from config.settings import get_settings, mask_secret
    from youtube_pipeline.orchestrator import VideoPipelineOrchestrator

    get_settings.cache_clear()
    settings = get_settings()
    setup_logging("DEBUG" if verbose else settings.log_level, force=True)

    logger.info("Env file: %s (exists=%s)", _ENV_FILE, _ENV_FILE.exists())
    if settings.llm_provider.value == "groq":
        logger.info("GROQ_API_KEY loaded: %s", mask_secret(settings.groq_api_key))

    if settings.llm_provider.value == "groq" and not settings.groq_api_key:
        console.print("[red]Missing required environment variable:[/red] GROQ_API_KEY")
        console.print(
            f"Create [cyan]{_ENV_FILE}[/cyan] with:\n"
            "  GROQ_API_KEY=gsk_your_key_here\n"
            "Get a free key at https://console.groq.com/keys"
        )
        raise typer.Exit(code=1)
    if settings.tts_provider.value == "openai" and not settings.openai_api_key:
        console.print(
            "[red]Missing required environment variable:[/red] OPENAI_API_KEY "
            "(needed for OpenAI TTS)"
        )
        console.print("Copy [cyan].env.example[/cyan] → [cyan].env[/cyan] and fill in your keys.")
        raise typer.Exit(code=1)
    if settings.asset_provider.value == "openai_image" and not settings.openai_api_key:
        console.print("[red]Missing required environment variable:[/red] OPENAI_API_KEY")
        console.print("Required when ASSET_PROVIDER=openai_image")
        raise typer.Exit(code=1)
    # ASSET_PROVIDER=pollinations is free/keyless — no key check needed.

    request = PipelineRequest(
        idea=idea,
        style=style,
        aspect_ratio=aspect_ratio,
        target_duration_seconds=duration,
        max_scenes=max_scenes,
        voice=voice,
        output_name=output_name,
        burn_captions=not no_captions,
        enable_ken_burns=not no_ken_burns,
    )

    logger.info("Idea: %s", request.idea)
    logger.info("Style: %s", request.style.value)
    logger.info(
        "Providers — LLM: %s (%s) | TTS: %s | Assets: %s | Captions: Pillow",
        settings.llm_provider.value,
        settings.llm_model,
        settings.tts_provider.value,
        settings.asset_provider.value,
    )
    logger.info(
        "Pipeline plan — 5 stages: Script → Audio → Assets → Localize → MoviePy compile"
    )

    orchestrator = VideoPipelineOrchestrator(settings=settings)
    try:
        result = orchestrator.run(request)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Pipeline failed")
        console.print(f"\n[red]Pipeline failed:[/red] {exc}")
        if "invalid_api_key" in str(exc).lower() or "GROQ_API_KEY" in str(exc):
            console.print(
                "\n[yellow]Tip:[/yellow] run [cyan]python cli.py doctor[/cyan] to verify "
                "your .env key loading, then grab a fresh key at "
                "https://console.groq.com/keys"
            )
        raise typer.Exit(code=1) from exc

    console.print("\n[green]Pipeline complete[/green]")
    console.print(f"  Status : {result.status}")
    console.print(f"  Video  : {result.video_path}")
    if run_dir := result.metadata.get("run_dir"):
        console.print(f"  Run    : {run_dir}")
    if scenes := result.metadata.get("scene_count"):
        console.print(f"  Scenes : {scenes}")
    if phrases := result.metadata.get("caption_phrases"):
        console.print(f"  Captions: {phrases} dynamic phrases (Pillow renderer)")


@app.command("doctor")
def doctor() -> None:
    """Diagnose .env loading and API key configuration (secrets are masked)."""
    from config.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    console.print("[bold]AIVideo environment doctor[/bold]\n")
    console.print(f".env path : {_ENV_FILE}")
    console.print(f".env exists: {_ENV_FILE.exists()}")
    console.print(f"cwd       : {Path.cwd()}")
    console.print(f"LLM       : {settings.llm_provider.value} / {settings.llm_model}")
    console.print(f"TTS       : {settings.tts_provider.value}")
    console.print(f"Assets    : {settings.asset_provider.value}")
    console.print("")
    for name, preview in settings.describe_secrets().items():
        console.print(f"  {name:18} {preview}")

    if not settings.groq_api_key and settings.llm_provider.value == "groq":
        console.print("\n[red]Missing GROQ_API_KEY[/red] — script generation will fail.")
        console.print("Get a free key at https://console.groq.com/keys")

    console.print("\n[dim]Recommended free local .env (no quotes):[/dim]")
    console.print("  GROQ_API_KEY=gsk_your_real_key")
    console.print("  TTS_PROVIDER=edge-tts")
    console.print("  EDGE_TTS_VOICE=en-US-ChristopherNeural")
    console.print("  LLM_PROVIDER=groq")
    console.print("  ASSET_PROVIDER=pollinations")
    console.print("\n[dim]After merging main: remove PIXABAY_API_KEY / PEXELS_API_KEY;")
    console.print("ASSET_PROVIDER=pixabay|pexels is auto-remapped to pollinations.[/dim]")


@app.command("styles")
def styles() -> None:
    """List supported visual styles."""
    for item in VisualStyle:
        console.print(f"- {item.value}")


if __name__ == "__main__":
    app()
