"""YouTube video automation pipeline."""

from youtube_pipeline.models import (
    PipelineRequest,
    PipelineResult,
    SceneData,
    VideoScript,
    VisualStyle,
)

__all__ = [
    "PipelineRequest",
    "PipelineResult",
    "SceneData",
    "VideoScript",
    "VisualStyle",
    "VideoPipelineOrchestrator",
]

__version__ = "0.1.0"


def __getattr__(name: str):
    # Lazy export keeps lightweight imports (models/tests) from pulling MoviePy.
    if name == "VideoPipelineOrchestrator":
        from youtube_pipeline.orchestrator import VideoPipelineOrchestrator

        return VideoPipelineOrchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
