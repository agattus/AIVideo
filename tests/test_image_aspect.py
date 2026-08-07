from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from config.settings import AssetProvider
from youtube_pipeline.assets import hitl_workspace
from youtube_pipeline.assets.image_aspect import (
    aspect_prompt_clause,
    normalize_image_to_aspect,
    target_size,
)
from youtube_pipeline.models import MediaAsset
from youtube_pipeline.utils.files import write_json


def test_target_size_vertical():
    w, h = target_size("9:16", long_edge=1280)
    assert h > w
    assert abs((h / w) - (16 / 9)) < 0.02


def test_normalize_crops_landscape_to_portrait():
    img = Image.new("RGB", (1600, 900), color=(20, 20, 20))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    out = normalize_image_to_aspect(buf.getvalue(), "9:16")
    result = Image.open(BytesIO(out))
    assert result.height > result.width
    assert abs((result.height / result.width) - (16 / 9)) < 0.05


def test_aspect_prompt_mentions_vertical():
    clause = aspect_prompt_clause("9:16")
    assert "9:16" in clause or "vertical" in clause.lower()


class _RecordingProvider:
    name = "fake"

    def __init__(self) -> None:
        self.aspects: list[str] = []

    def fetch_for_scene(self, scene, output_dir: Path, *, aspect_ratio: str = "16:9"):
        self.aspects.append(aspect_ratio)
        path = output_dir / f"scene_{scene.scene_id:02d}.jpg"
        Image.new("RGB", (1600, 900), color=(30, 60, 90)).save(path, format="JPEG")
        return MediaAsset(
            scene_id=scene.scene_id,
            path=str(path),
            source=self.name,
            media_type="image",
        )


def _portrait_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_json(run_dir / "request.json", {"aspect_ratio": "9:16"})
    write_json(
        run_dir / "prompts.json",
        {
            "aspect_ratio": "9:16",
            "scene_count": 1,
            "scenes": [
                {
                    "scene_id": 0,
                    "script_text": "Narration",
                    "visual_prompt": "A portrait scene",
                }
            ],
        },
    )
    return run_dir


def _install_recording_provider(monkeypatch):
    provider = _RecordingProvider()
    monkeypatch.setattr(
        hitl_workspace,
        "get_settings",
        lambda: SimpleNamespace(asset_provider=AssetProvider.GEMINI_IMAGE),
    )
    monkeypatch.setattr(hitl_workspace, "build_asset_provider", lambda settings: provider)
    return provider


def test_auto_fill_passes_aspect_to_provider_and_normalizes_saved_image(
    tmp_path, monkeypatch
):
    run_dir = _portrait_run(tmp_path)
    provider = _install_recording_provider(monkeypatch)

    result = hitl_workspace.auto_fill_scene_images(run_dir)

    assert result["filled"] == 1
    assert provider.aspects == ["9:16"]
    with Image.open(run_dir / "assets" / "scene_00.jpg") as image:
        assert image.height > image.width


def test_single_scene_generate_passes_aspect_to_provider_and_normalizes_saved_image(
    tmp_path, monkeypatch
):
    run_dir = _portrait_run(tmp_path)
    provider = _install_recording_provider(monkeypatch)

    result = hitl_workspace.generate_one_scene_image(run_dir, 0)

    assert result["filled"] == 1
    assert provider.aspects == ["9:16"]
    with Image.open(run_dir / "assets" / "scene_00.jpg") as image:
        assert image.height > image.width
