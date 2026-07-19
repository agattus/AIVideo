from __future__ import annotations

from pathlib import Path

from youtube_pipeline.models import (
    AudioArtifact,
    MediaAsset,
    Scene,
    ScriptPackage,
    VisualStyle,
)
from youtube_pipeline.video.timing import align_scenes_to_audio


def test_align_scenes_covers_full_audio() -> None:
    scenes = [
        Scene(index=0, narration="Short", visual_prompt="prompt a", keywords=["a"]),
        Scene(
            index=1,
            narration="A much longer narration for weighting",
            visual_prompt="prompt b",
            keywords=["b"],
            duration_hint_seconds=8,
        ),
    ]
    script = ScriptPackage(
        title="t",
        idea="idea",
        style=VisualStyle.DOCUMENTARY,
        full_script="Short A much longer narration for weighting",
        scenes=scenes,
    )
    audio = AudioArtifact(
        audio_path=Path("voice.mp3"),
        duration_seconds=10.0,
    )
    assets = [
        MediaAsset(scene_index=0, path=Path("a.jpg"), source="test", media_type="image"),
        MediaAsset(scene_index=1, path=Path("b.jpg"), source="test", media_type="image"),
    ]

    timed = align_scenes_to_audio(script, audio, assets)
    assert len(timed) == 2
    assert timed[0].start == 0.0
    assert timed[-1].end == 10.0
    assert timed[0].end == timed[1].start
    assert timed[1].asset is not None
    assert timed[1].asset.scene_index == 1
