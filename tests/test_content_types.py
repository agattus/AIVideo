"""Content type + quiz form presets."""

from __future__ import annotations

from youtube_pipeline.content_types import (
    apply_form_defaults,
    content_type_catalog,
    normalize_content_type,
    preset_for,
    question_count_for,
)
from youtube_pipeline.models import ContentType, FormLength, SceneData, VideoScript


def test_normalize_content_type_aliases() -> None:
    assert normalize_content_type("quizverse") == ContentType.QUIZ
    assert normalize_content_type("trivia") == ContentType.QUIZ
    assert normalize_content_type("story") == ContentType.NARRATION


def test_quiz_short_preset() -> None:
    preset = preset_for("quiz", "short")
    assert preset["questions"] == 3
    assert preset["max_scenes"] == 6
    assert preset["hold_seconds"] == 10
    assert preset["aspect_ratio"].value == "9:16"


def test_apply_form_defaults_fills_quiz_even_scenes() -> None:
    data = apply_form_defaults(
        {"idea": "Solar system trivia", "content_type": "quiz", "form_length": "short"}
    )
    assert data["content_type"] == "quiz"
    assert data["max_scenes"] == 6
    assert data["duration"] == 75
    assert data["aspect_ratio"] == "9:16"
    assert question_count_for(data["max_scenes"], content_type=ContentType.QUIZ) == 3


def test_explicit_duration_wins_over_preset() -> None:
    data = apply_form_defaults(
        {
            "idea": "Black holes",
            "content_type": "narration",
            "form_length": "short",
            "duration": 90,
            "aspect_ratio": "16:9",
        }
    )
    assert data["duration"] == 90
    assert data["aspect_ratio"] == "16:9"


def test_catalog_has_four_presets() -> None:
    catalog = content_type_catalog()
    assert len(catalog) == 4
    ids = {(row["content_type"], row["form_length"]) for row in catalog}
    assert ("quiz", "short") in ids
    assert ("narration", "long") in ids


def test_quiz_scene_model_fields() -> None:
    scene = SceneData(
        scene_id=0,
        script_text="What is the largest planet?",
        visual_prompt="Bold space quiz background",
        phase="question",
        question="What is the largest planet in our solar system?",
        hold_seconds=10,
    )
    assert scene.phase == "question"
    assert scene.hold_seconds == 10
    script = VideoScript(
        title="Space Quiz",
        full_script=scene.script_text,
        style="fast_paced_shorts",
        scenes=[scene],
    )
    assert script.scenes[0].question is not None


def test_content_types_endpoint() -> None:
    from fastapi.testclient import TestClient
    from youtube_pipeline.api.main import app

    client = TestClient(app)
    res = client.get("/api/v1/content-types")
    assert res.status_code == 200
    body = res.json()
    assert body["default_content_type"] == "narration"
    assert any(ct["id"] == "quiz" for ct in body["content_types"])
