"""Tests for ZIP ingest and FFmpegComposer helpers."""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from youtube_pipeline.assets.prompts_export import export_visual_prompts
from youtube_pipeline.assets.zip_ingest import (
    find_scene_image,
    ingest_assets_zip,
    normalize_loose_scene_images,
    validate_scene_images,
)
from youtube_pipeline.exceptions import AssetAcquisitionError, VideoCompositionError
from youtube_pipeline.models import SceneData, VideoScript
from youtube_pipeline.video.ffmpeg_composer import FFmpegComposer


def _script(n: int = 2) -> VideoScript:
    scenes = [
        SceneData(
            scene_id=i,
            script_text=f"Line {i}",
            visual_prompt=f"visual {i}",
            duration=1.0,
        )
        for i in range(n)
    ]
    return VideoScript(
        title="HITL",
        full_script=" ".join(s.script_text for s in scenes),
        style="cinematic",
        scenes=scenes,
    )


def _jpg(path: Path, color=(40, 90, 140)) -> None:
    Image.new("RGB", (48, 48), color).save(path, format="JPEG")


def test_export_visual_prompts_writes_json_and_csv(tmp_path: Path) -> None:
    payload = export_visual_prompts(_script(), tmp_path, aspect_ratio="9:16")
    assert payload["scene_count"] == 2
    assert payload["aspect_ratio"] == "9:16"
    assert (tmp_path / "prompts.json").exists()
    assert (tmp_path / "prompts.csv").exists()
    csv_text = (tmp_path / "prompts.csv").read_text(encoding="utf-8")
    assert "scene_number" in csv_text
    assert "visual_prompt" in csv_text


def test_ingest_assets_zip_renames_and_validates(tmp_path: Path) -> None:
    zip_path = tmp_path / "a.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for i in range(2):
            img = tmp_path / f"tmp_{i}.jpg"
            _jpg(img, (10 + i * 30, 50, 90))
            zf.write(img, arcname=f"scene_{i:02d}.jpg")

    assets = tmp_path / "assets"
    paths = ingest_assets_zip(zip_path, assets, expected_scenes=2)
    assert len(paths) == 2
    assert (assets / "scene_00.jpg").exists()
    assert (assets / "scene_01.jpg").exists()
    validate_scene_images(assets, expected_scenes=2)


def test_find_and_normalize_loose_scene_filenames(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    # Browser / Flow downloads often append a token after the extension.
    weird = assets / "scene_00.jpg_1730123456789"
    _jpg(weird, (20, 80, 120))
    weird2 = assets / "scene_01.jpg_202608012052.jpeg"
    _jpg(weird2, (90, 40, 10))
    # Must not treat scene_10 as scene_1.
    weird10 = assets / "scene_10.jpg_token.jpeg"
    _jpg(weird10, (1, 2, 3))

    assert find_scene_image(assets, 0) == weird
    assert find_scene_image(assets, 1) == weird2
    assert find_scene_image(assets, 10) == weird10

    written = normalize_loose_scene_images(assets, expected_scenes=11)
    assert (assets / "scene_00.jpg").exists()
    assert (assets / "scene_01.jpg").exists()
    assert (assets / "scene_10.jpg").exists()
    assert not weird.exists()
    assert not weird2.exists()
    assert not weird10.exists()
    assert len(written) >= 3


def test_ingest_assets_zip_accepts_jpg_suffix_token(tmp_path: Path) -> None:
    zip_path = tmp_path / "weird.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for i in range(2):
            img = tmp_path / f"tmp_{i}.jpg"
            _jpg(img, (10 + i * 30, 50, 90))
            zf.write(img, arcname=f"scene_{i:02d}.jpg_downloadtoken")

    assets = tmp_path / "assets"
    paths = ingest_assets_zip(zip_path, assets, expected_scenes=2)
    assert len(paths) == 2
    validate_scene_images(assets, expected_scenes=2)


def test_ingest_assets_zip_count_mismatch(tmp_path: Path) -> None:
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        img = tmp_path / "only.jpg"
        _jpg(img)
        zf.write(img, arcname="scene_00.jpg")

    with pytest.raises(AssetAcquisitionError, match="expects 2"):
        ingest_assets_zip(zip_path, tmp_path / "assets", expected_scenes=2)


def test_ffmpeg_composer_builds_zoompan_command(tmp_path: Path) -> None:
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
        burn_captions=True,
        aspect_ratio="16:9",
    )
    calls: list[list[str]] = []

    def fake_run(cmd, capture_output=True, text=True, check=False):
        calls.append(cmd)
        # Pretend success and create expected outputs when writing files.
        dest = Path(cmd[-1])
        if dest.suffix == ".mp4":
            dest.write_bytes(b"\x00" * 512)
        class P:
            returncode = 0
            stderr = ""
            stdout = ""
        return P()

    with patch("youtube_pipeline.video.ffmpeg_composer.subprocess.run", side_effect=fake_run):
        result = composer.compose(_script(2), audio, assets, out)

    assert result.status == "success"
    assert any("zoompan" in " ".join(c) for c in calls)
    assert any("overlay" in " ".join(c) for c in calls)
    assert result.metadata["burn_captions"] is True
    assert result.metadata["aspect_ratio"] == "16:9"
    assert result.metadata["width"] == 640
    assert result.metadata["height"] == 360
    assert out.exists()
    assert out.with_suffix(".srt").exists()


def test_ffmpeg_composer_vertical_aspect_dimensions(tmp_path: Path) -> None:
    from config.settings import Settings

    composer = FFmpegComposer(
        Settings(output_dir=tmp_path / "o", assets_cache_dir=tmp_path / "c"),
        width=1080,
        height=1920,
        aspect_ratio="9:16",
        burn_captions=False,
    )
    assert composer.width == 1080
    assert composer.height == 1920
    assert composer.aspect_ratio == "9:16"


def test_ffmpeg_composer_missing_image_raises(tmp_path: Path) -> None:
    from config.settings import Settings

    assets = tmp_path / "assets"
    assets.mkdir()
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"ID3" + b"\x00" * 1024)
    composer = FFmpegComposer(
        Settings(output_dir=tmp_path / "o", assets_cache_dir=tmp_path / "c")
    )
    with pytest.raises(VideoCompositionError, match="Missing image"):
        composer.compose(_script(1), audio, assets, tmp_path / "x.mp4")
