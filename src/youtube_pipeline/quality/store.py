"""Read and write persisted quality reviews."""

from __future__ import annotations

from pathlib import Path

from youtube_pipeline.quality.models import QualityReview
from youtube_pipeline.utils.files import read_json, write_json


_REVIEW_FILENAME = "quality_review.json"


def save_quality_review(run_dir: Path | str, review: QualityReview) -> Path:
    """Persist a quality review in a pipeline run directory."""
    review.mark_overrides_approved()
    return write_json(Path(run_dir) / _REVIEW_FILENAME, review.model_dump())


def load_quality_review(run_dir: Path | str) -> QualityReview:
    """Load a quality review from a pipeline run directory."""
    payload = read_json(Path(run_dir) / _REVIEW_FILENAME)
    return QualityReview.model_validate(payload)
