import json
from pathlib import Path

from youtube_pipeline.assets.scene_reorder import reorder_scenes


def _write_fixture(run: Path) -> None:
    script = {
        "title": "t",
        "full_script": "A. B. C.",
        "style": "cinematic",
        "scenes": [
            {"scene_id": 0, "script_text": "A.", "visual_prompt": "va", "duration": 1.5},
            {"scene_id": 1, "script_text": "B.", "visual_prompt": "vb", "duration": 2.0},
            {"scene_id": 2, "script_text": "C.", "visual_prompt": "vc", "duration": 1.0},
        ],
    }
    timing = {
        "total_duration": 4.5,
        "scenes": [
            {"scene_id": 0, "start": 0.0, "end": 1.5, "duration": 1.5, "speech_duration": 1.5, "pause_after": 0.0},
            {"scene_id": 1, "start": 1.5, "end": 3.5, "duration": 2.0, "speech_duration": 2.0, "pause_after": 0.0},
            {"scene_id": 2, "start": 3.5, "end": 4.5, "duration": 1.0, "speech_duration": 1.0, "pause_after": 0.0},
        ],
        "words": [],
    }
    (run / "script.json").write_text(json.dumps(script), encoding="utf-8")
    (run / "script_timed.json").write_text(json.dumps(script), encoding="utf-8")
    (run / "timing.json").write_text(json.dumps(timing), encoding="utf-8")


def test_reorder_permutes_script_and_retimes(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    reorder_scenes(tmp_path, [2, 0, 1])
    script = json.loads((tmp_path / "script.json").read_text(encoding="utf-8"))
    assert [s["scene_id"] for s in script["scenes"]] == [2, 0, 1]
    timing = json.loads((tmp_path / "timing.json").read_text(encoding="utf-8"))
    assert [s["scene_id"] for s in timing["scenes"]] == [2, 0, 1]
    assert timing["scenes"][0]["start"] == 0.0
    assert timing["scenes"][0]["duration"] == 1.0
    assert abs(timing["total_duration"] - 4.5) < 0.01


def test_reorder_rejects_bad_permutation(tmp_path: Path) -> None:
    import pytest

    _write_fixture(tmp_path)
    with pytest.raises(ValueError):
        reorder_scenes(tmp_path, [0, 1])
