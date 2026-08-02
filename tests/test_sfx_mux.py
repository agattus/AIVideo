"""Tests for the scene ambience/one-shot FFmpeg filter builder and mux wiring."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from youtube_pipeline.models import SceneData, SfxCue, VideoScript
from youtube_pipeline.video.ffmpeg_composer import FFmpegComposer
from youtube_pipeline.video.sfx_mix import build_sfx_filter_complex

PACK_ROOT = Path(__file__).resolve().parents[1] / "assets" / "sfx"
RAIN_MP3 = PACK_ROOT / "ambiences" / "rain.mp3"
THUNDER_MP3 = PACK_ROOT / "oneshots" / "thunder.mp3"


def _scenes_with_sfx() -> list[SceneData]:
    return [
        SceneData(scene_id=0, script_text="Calm before", visual_prompt="wide shot", ambience="none"),
        SceneData(
            scene_id=1,
            script_text="Storm rolls in",
            visual_prompt="storm",
            ambience="rain",
            sfx=[SfxCue(tag="thunder", at=0.4)],
        ),
    ]


def test_build_sfx_filter_includes_adelay_and_amix() -> None:
    scenes = _scenes_with_sfx()
    durations = [5.0, 5.0]

    filter_complex = build_sfx_filter_complex(
        scene_durations=durations,
        scenes=scenes,
        has_bgm=False,
        ambience_inputs=[(2, RAIN_MP3)],
        oneshot_inputs=[(3, THUNDER_MP3, (5.0 + 0.4 * 5.0) * 1000.0)],
    )

    assert "aloop" in filter_complex
    assert "adelay=5000" in filter_complex  # scene 1 starts at t=5s
    assert "adelay=7000" in filter_complex  # 5s + 0.4*5s = 7s
    assert "volume=0.12" in filter_complex
    assert "volume=0.35" in filter_complex
    assert filter_complex.count("amix") >= 1
    assert filter_complex.endswith("[a]")
    assert "[2:a]" in filter_complex
    assert "[3:a]" in filter_complex


def test_build_sfx_filter_includes_bgm_bus_when_present() -> None:
    scenes = _scenes_with_sfx()
    filter_complex = build_sfx_filter_complex(
        scene_durations=[5.0, 5.0],
        scenes=scenes,
        has_bgm=True,
        ambience_inputs=[(3, RAIN_MP3)],
        oneshot_inputs=[],
    )

    assert "[2:a]aloop=loop=-1:size=2e+09,volume=0.1" in filter_complex
    assert "[bg]" in filter_complex
    assert "[3:a]" in filter_complex


def test_build_sfx_filter_no_sfx_still_ends_with_mixed_bus() -> None:
    scenes = [
        SceneData(scene_id=0, script_text="Hello", visual_prompt="wide shot", ambience="none"),
    ]
    filter_complex = build_sfx_filter_complex(
        scene_durations=[3.0],
        scenes=scenes,
        has_bgm=False,
        ambience_inputs=[],
        oneshot_inputs=[],
    )

    assert filter_complex == "[1:a]volume=1.05[vo];[vo]amix=inputs=1:duration=first:dropout_transition=2[a]"


def _jpg(path: Path, color=(40, 90, 140)) -> None:
    Image.new("RGB", (48, 48), color).save(path, format="JPEG")


def _fake_run(cmd, capture_output=True, text=True, check=False):
    dest = Path(cmd[-1])
    if dest.suffix in {".mp4"}:
        dest.write_bytes(b"\x00" * 512)

    class _P:
        returncode = 0
        stderr = ""
        stdout = ""

    return _P()


@pytest.mark.skipif(not RAIN_MP3.exists(), reason="bundled sfx pack not present")
def test_mux_audio_adds_sfx_inputs_when_scene_ambience_resolves(tmp_path: Path) -> None:
    from config.settings import Settings

    assets = tmp_path / "assets"
    assets.mkdir()
    for i in range(2):
        _jpg(assets / f"scene_{i:02d}.jpg", (20 * i, 80, 120))
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"ID3" + b"\x00" * 2048)
    out = tmp_path / "out.mp4"

    composer = FFmpegComposer(
        Settings(output_dir=tmp_path / "o", assets_cache_dir=tmp_path / "c"),
        width=640,
        height=360,
        fps=24,
        burn_captions=False,
        aspect_ratio="16:9",
    )

    scenes = _scenes_with_sfx()
    for scene in scenes:
        scene.duration = 1.0
    script = VideoScript(
        title="Storm",
        full_script=" ".join(s.script_text for s in scenes),
        style="cinematic",
        scenes=scenes,
    )

    calls: list[list[str]] = []

    def fake_run(cmd, capture_output=True, text=True, check=False):
        calls.append(cmd)
        return _fake_run(cmd, capture_output=capture_output, text=text, check=check)

    with patch("youtube_pipeline.video.ffmpeg_composer.subprocess.run", side_effect=fake_run):
        result = composer.compose(script, audio, assets, out)

    assert result.status == "success"
    mux_call = next(c for c in calls if str(RAIN_MP3) in c)
    assert str(THUNDER_MP3) in mux_call
    assert "-filter_complex" in mux_call


def test_mux_audio_keeps_legacy_path_when_no_sfx_resolves(tmp_path: Path) -> None:
    from config.settings import Settings

    assets = tmp_path / "assets"
    assets.mkdir()
    for i in range(2):
        _jpg(assets / f"scene_{i:02d}.jpg", (20 * i, 80, 120))
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"ID3" + b"\x00" * 2048)
    out = tmp_path / "out.mp4"

    composer = FFmpegComposer(
        Settings(output_dir=tmp_path / "o", assets_cache_dir=tmp_path / "c"),
        width=640,
        height=360,
        fps=24,
        burn_captions=False,
        aspect_ratio="16:9",
    )

    scenes = [
        SceneData(scene_id=i, script_text=f"Line {i}", visual_prompt=f"visual {i}", duration=1.0)
        for i in range(2)
    ]
    script = VideoScript(
        title="Plain",
        full_script=" ".join(s.script_text for s in scenes),
        style="cinematic",
        scenes=scenes,
    )

    calls: list[list[str]] = []

    def fake_run(cmd, capture_output=True, text=True, check=False):
        calls.append(cmd)
        return _fake_run(cmd, capture_output=capture_output, text=text, check=check)

    with patch("youtube_pipeline.video.ffmpeg_composer.subprocess.run", side_effect=fake_run):
        result = composer.compose(script, audio, assets, out)

    assert result.status == "success"
    mux_call = calls[-1]
    assert "-filter_complex" not in mux_call
    assert mux_call.count("-i") == 2  # video + voiceover only, no sfx/bgm inputs
