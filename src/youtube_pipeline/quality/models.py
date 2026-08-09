"""Persisted models for pipeline quality reviews."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ReviewStatus = Literal["pass", "needs_approval", "overridden", "pending"]


class StageReview(BaseModel):
    """Fields shared by script and timing reviews."""

    model_config = ConfigDict(validate_assignment=True)

    status: ReviewStatus = "pending"
    issues: list[str] = Field(default_factory=list)


class ScriptReview(StageReview):
    """Script rubric results."""

    scores: dict[str, int] = Field(default_factory=dict)
    retries: int = 0


class TimingReview(StageReview):
    """Deterministic timing review results."""


class ImageReview(BaseModel):
    """Per-scene image aptness results."""

    model_config = ConfigDict(validate_assignment=True)

    status: ReviewStatus = "pending"
    scenes: dict[str, Any] = Field(default_factory=dict)
    retries: dict[str, int] = Field(default_factory=dict)


def _default_approvals() -> dict[str, bool]:
    return {"script": False, "timing": False, "images": False}


class QualityReview(BaseModel):
    """Complete quality review document for one pipeline run."""

    script_review: ScriptReview = Field(default_factory=ScriptReview)
    timing_review: TimingReview = Field(default_factory=TimingReview)
    image_review: ImageReview = Field(default_factory=ImageReview)
    approvals: dict[str, bool] = Field(default_factory=_default_approvals)

    def mark_overrides_approved(self) -> None:
        """Keep approval flags consistent with overridden stage statuses."""
        if self.script_review.status == "overridden":
            self.approvals["script"] = True
        if self.timing_review.status == "overridden":
            self.approvals["timing"] = True
        if self.image_review.status == "overridden":
            self.approvals["images"] = True
