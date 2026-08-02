from __future__ import annotations

from pathlib import Path

from youtube_pipeline.audio.sfx_pack import (
    resolve_ambience_path,
    resolve_oneshot_path,
)
from youtube_pipeline.audio.sfx_tags import (
    apply_sfx_fallback,
    infer_sfx_from_text,
    normalize_ambience,
    normalize_sfx,
)
from youtube_pipeline.models import SceneData, SfxCue


def test_scene_sfx_defaults_preserve_old_payloads() -> None:
    scene = SceneData(scene_id=0, script_text="Hello", visual_prompt="Wide shot")

    assert scene.ambience == "none"
    assert scene.sfx == []


def test_scene_normalizes_unknown_tags_and_cue_positions() -> None:
    scene = SceneData(
        scene_id=0,
        script_text="Hello",
        visual_prompt="Wide shot",
        ambience=" Spaceship ",
        sfx=[
            {"tag": " THUNDER ", "at": 0.01},
            {"tag": "unknown", "at": 0.5},
            {"tag": "door", "at": 0.99},
            {"tag": "birds", "at": 0.4},
        ],
    )

    assert scene.ambience == "none"
    assert scene.sfx == [
        SfxCue(tag="thunder", at=0.15),
        SfxCue(tag="door", at=0.85),
    ]


def test_normalize_helpers_handle_invalid_values() -> None:
    assert normalize_ambience(None) == "none"
    assert normalize_ambience(" Forest ") == "forest"
    assert normalize_ambience("spaceship") == "none"
    assert normalize_sfx(None) == []
    assert normalize_sfx([None, "thunder", {"tag": "nope", "at": 0.5}]) == []


def test_normalize_sfx_clamps_and_limits() -> None:
    cues = normalize_sfx(
        [
            {"tag": "thunder", "at": 0.01},
            {"tag": "whoosh", "at": 0.99},
            {"tag": "door", "at": 0.5},
        ]
    )

    assert cues == [
        SfxCue(tag="thunder", at=0.15),
        SfxCue(tag="whoosh", at=0.85),
    ]


def test_keyword_inference_uses_script_and_visual_text() -> None:
    ambience, sfx = infer_sfx_from_text(
        "Lightning flashes over the road",
        "Heavy rain on wet streets",
    )

    assert ambience == "rain"
    assert sfx == [SfxCue(tag="thunder", at=0.45)]


def test_keyword_inference_covers_supported_ambiences() -> None:
    cases = {
        "trees in a jungle": "forest",
        "traffic on a busy street": "city",
        "waves roll onto the beach": "ocean",
        "a glowing campfire": "fire",
        "the midnight moon": "night",
        "a strong gale": "wind",
        "quiet indoor office": "room",
        "abstract shapes": "none",
    }

    for text, expected in cases.items():
        ambience, _ = infer_sfx_from_text(text)
        assert ambience == expected


def test_keyword_inference_limits_oneshots() -> None:
    ambience, sfx = infer_sfx_from_text(
        "Thunder, footsteps, a door, birds, cheering crowd, and a whoosh in rain"
    )

    assert ambience == "rain"
    assert len(sfx) == 2
    assert all(cue.tag in {"thunder", "footsteps", "door", "birds", "crowd_cheer", "whoosh"} for cue in sfx)


def test_apply_fallback_fills_only_an_empty_untagged_scene() -> None:
    empty = SceneData(
        scene_id=0,
        script_text="Thunder rolls through rain",
        visual_prompt="storm",
    )
    existing = SceneData(
        scene_id=1,
        script_text="Rain falls",
        visual_prompt="storm",
        ambience="forest",
        sfx=[SfxCue(tag="birds", at=0.5)],
    )

    filled = apply_sfx_fallback(empty)
    preserved = apply_sfx_fallback(existing)

    assert filled.ambience == "rain"
    assert filled.sfx == [SfxCue(tag="thunder", at=0.45)]
    assert preserved == existing


def test_pack_resolvers_soft_fail_for_unknown_or_missing_files(tmp_path: Path) -> None:
    ambience_file = tmp_path / "ambiences" / "rain.mp3"
    oneshot_file = tmp_path / "oneshots" / "door.mp3"
    ambience_file.parent.mkdir()
    oneshot_file.parent.mkdir()
    ambience_file.write_bytes(b"rain")
    oneshot_file.write_bytes(b"door")

    assert resolve_ambience_path("RAIN", tmp_path) == ambience_file
    assert resolve_oneshot_path(" door ", tmp_path) == oneshot_file
    assert resolve_ambience_path("unknown", tmp_path) is None
    assert resolve_oneshot_path("thunder", tmp_path) is None
