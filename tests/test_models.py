from __future__ import annotations

import pytest
from pydantic import ValidationError

from youtube_pipeline.models import Scene, ScriptPackage, VisualStyle


def test_script_package_requires_scenes() -> None:
    with pytest.raises(ValidationError):
        ScriptPackage(
            title="Empty",
            idea="x",
            style=VisualStyle.CINEMATIC,
            full_script="hi",
            scenes=[],
        )


def test_scene_keyword_normalization() -> None:
    scene = Scene(
        index=0,
        narration="Hello world",
        visual_prompt="A wide cinematic shot of a coastline at golden hour",
        keywords=[" Ocean ", "CLIFF", ""],
    )
    assert scene.keywords == ["ocean", "cliff"]
