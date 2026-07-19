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

# Load .env before Settings / orchestrator read API keys.
load_dotenv(ROOT / ".env", override=False)
load_dotenv(override=False)

import typer
from rich.console import Console

from youtube_pipeline.models import AspectRatio, PipelineRequest, VisualStyle
from youtube_pipeline.orchestrator import VideoPipelineOrchestrator

app = typer.Typer(
    add_completion=False,
    help="Generate a complete YouTube video from an idea and visual style.",
)
console = Console()


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
        max=1200,
        help="Target duration in seconds",
    ),
    max_scenes: int = typer.Option(8, "--max-scenes", min=2, max=30),
    voice: str | None = typer.Option(None, "--voice", help="Override TTS voice id/name"),
    output_name: str | None = typer.Option(None, "--name", help="Output basename"),
    no_captions: bool = typer.Option(False, "--no-captions", help="Disable burned-in captions"),
    no_ken_burns: bool = typer.Option(False, "--no-ken-burns", help="Disable Ken Burns motion"),
) -> None:
    """Run the full automation pipeline end-to-end.

    Example::

        python cli.py generate "How black holes warp spacetime" --style cinematic
    """
    # Ensure Settings sees the latest env after dotenv load.
    from config.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    if not settings.openai_api_key:
        console.print("[red]Missing required environment variable:[/red] OPENAI_API_KEY")
        console.print("Copy [cyan].env.example[/cyan] → [cyan].env[/cyan] and fill in your keys.")
        raise typer.Exit(code=1)
    if not settings.pexels_api_key:
        console.print(
            "[yellow]Warning:[/yellow] PEXELS_API_KEY unset — "
            "AssetService will fall back to OpenAI DALL·E 3 for every scene."
        )

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

    console.print(f"[bold]Idea[/bold]:  {request.idea}")
    console.print(f"[bold]Style[/bold]: {request.style.value}")
    console.print(
        f"[dim]Providers — LLM/TTS: {settings.llm_provider.value} / "
        f"{settings.tts_provider.value} | Assets: Pexels→DALL·E fallback[/dim]"
    )
    console.print("Starting pipeline...")

    orchestrator = VideoPipelineOrchestrator(settings=settings)
    try:
        result = orchestrator.run(request)
    except Exception as exc:  # noqa: BLE001
        console.print(f"\n[red]Pipeline failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print("\n[green]Pipeline complete[/green]")
    console.print(f"  Status : {result.status}")
    console.print(f"  Video  : {result.video_path}")
    if run_dir := result.metadata.get("run_dir"):
        console.print(f"  Run    : {run_dir}")
    if scenes := result.metadata.get("scene_count"):
        console.print(f"  Scenes : {scenes}")


@app.command("styles")
def styles() -> None:
    """List supported visual styles."""
    for item in VisualStyle:
        console.print(f"- {item.value}")


if __name__ == "__main__":
    app()
