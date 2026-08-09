"""Assembly gate decisions for quality reviews."""

from __future__ import annotations

from youtube_pipeline.quality.models import QualityReview


def assemble_allowed(review: QualityReview) -> bool:
    """Return whether every quality stage passed or was overridden."""
    accepted = {"pass", "overridden"}
    return all(
        stage.status in accepted
        for stage in (
            review.script_review,
            review.timing_review,
            review.image_review,
        )
    )
