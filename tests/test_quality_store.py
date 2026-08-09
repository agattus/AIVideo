from __future__ import annotations


def test_assemble_allowed_requires_pass_or_override():
    from youtube_pipeline.quality.gate import assemble_allowed
    from youtube_pipeline.quality.models import QualityReview

    review = QualityReview()
    assert assemble_allowed(review) is False

    review.script_review.status = "pass"
    review.timing_review.status = "pass"
    review.image_review.status = "needs_approval"
    assert assemble_allowed(review) is False

    review.image_review.status = "overridden"
    assert assemble_allowed(review) is True


def test_round_trip_quality_review_json(tmp_path):
    from youtube_pipeline.quality.models import QualityReview
    from youtube_pipeline.quality.store import load_quality_review, save_quality_review

    review = QualityReview()
    review.script_review.status = "pass"
    review.script_review.scores = {
        "idea_fit": 4,
        "hook": 5,
        "ending": 4,
        "pacing_emotion": 3,
        "format_rules": 5,
    }

    saved_path = save_quality_review(tmp_path, review)
    loaded = load_quality_review(tmp_path)

    assert saved_path == tmp_path / "quality_review.json"
    assert loaded.script_review.status == "pass"
    assert loaded.script_review.scores["hook"] == 5


def test_save_marks_overridden_stages_approved(tmp_path):
    from youtube_pipeline.quality.models import QualityReview
    from youtube_pipeline.quality.store import load_quality_review, save_quality_review

    review = QualityReview()
    review.script_review.status = "overridden"
    review.timing_review.status = "overridden"
    review.image_review.status = "overridden"

    save_quality_review(tmp_path, review)
    loaded = load_quality_review(tmp_path)

    assert loaded.approvals == {
        "script": True,
        "timing": True,
        "images": True,
    }
