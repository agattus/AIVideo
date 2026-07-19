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
    """Run the full automation pipeline."""
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

    console.print(f"[bold]Idea[/bold]: {request.idea}")
    console.print(f"[bold]Style[/bold]: {request.style.value}")
    console.print("Starting pipeline...")

    orchestrator = VideoPipelineOrchestrator()
    result = orchestrator.run(request)

    console.print("\n[green]Pipeline complete[/green]")
    console.print(f"  Status : {result.status}")
    console.print(f"  Video  : {result.video_path}")
    if run_dir := result.metadata.get("run_dir"):
        console.print(f"  Run    : {run_dir}")


@app.command("styles")
def styles() -> None:
    """List supported visual styles."""
    for item in VisualStyle:
        console.print(f"- {item.value}")


if __name__ == "__main__":
    app()
