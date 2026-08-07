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


def test_auto_fill_continues_after_quota_error(tmp_path, monkeypatch):
    run_dir = _portrait_run(tmp_path)
    write_json(
        run_dir / "prompts.json",
        {
            "aspect_ratio": "9:16",
            "scene_count": 2,
            "scenes": [
                {
                    "scene_id": 0,
                    "script_text": "First line",
                    "visual_prompt": "First portrait scene",
                },
                {
                    "scene_id": 1,
                    "script_text": "Second line",
                    "visual_prompt": "Second portrait scene",
                },
            ],
        },
    )
    provider = _install_recording_provider(monkeypatch)
    successful_fetch = provider.fetch_for_scene

    def fail_first(scene, output_dir: Path, *, aspect_ratio: str = "16:9"):
        if scene.scene_id == 0:
            raise RuntimeError("429 quota exceeded")
        return successful_fetch(scene, output_dir, aspect_ratio=aspect_ratio)

    provider.fetch_for_scene = fail_first

    result = hitl_workspace.auto_fill_scene_images(run_dir)

    assert result["filled"] == 1
    assert result["failed"] == [{"scene_id": 0, "error": "429 quota exceeded"}]
    assert not (run_dir / "assets" / "scene_00.jpg").exists()
    assert (run_dir / "assets" / "scene_01.jpg").exists()


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


def test_openai_provider_uses_portrait_size_and_aspect_clause(monkeypatch, tmp_path):
    from youtube_pipeline.assets import ai_generator
    from youtube_pipeline.models import SceneData

    captured: dict[str, str] = {}

    class _FakeSettings:
        openai_api_key = "test-key"
        openai_image_model = "dall-e-3"

    provider = ai_generator.OpenAIImageProvider(settings=_FakeSettings())  # type: ignore[arg-type]

    def _fake_generate(self, prompt: str, *, size: str = "1792x1024") -> bytes:
        captured["prompt"] = prompt
        captured["size"] = size
        buf = BytesIO()
        Image.new("RGB", (1024, 1792), color=(10, 20, 30)).save(buf, format="PNG")
        return buf.getvalue()

    monkeypatch.setattr(ai_generator.OpenAIImageProvider, "_generate", _fake_generate)
    scene = SceneData(scene_id=0, script_text="Hi", visual_prompt="Moonlit fort gate")
    asset = provider.fetch_for_scene(scene, tmp_path, aspect_ratio="9:16")

    assert Path(asset.path).exists()
    assert captured["size"] == "1024x1792"
    assert "9:16" in captured["prompt"] or "vertical" in captured["prompt"].lower()


def test_pollinations_provider_forwards_aspect_dimensions(tmp_path):
    from youtube_pipeline.assets.pollinations import PollinationsProvider
    from youtube_pipeline.models import SceneData

    seen: dict[str, object] = {}

    class _FakeService:
        def _fetch_pollinations_image(self, scene, output_dir, *, aspect_ratio=None):
            seen["aspect_ratio"] = aspect_ratio
            path = Path(output_dir) / "scene_00.jpg"
            Image.new("RGB", (720, 1280), color=(40, 40, 40)).save(path, format="JPEG")
            return MediaAsset(
                scene_id=scene.scene_id,
                path=str(path),
                source="pollinations",
                media_type="image",
            )

    provider = PollinationsProvider.__new__(PollinationsProvider)
    provider._service = _FakeService()  # type: ignore[attr-defined]
    scene = SceneData(scene_id=0, script_text="Hi", visual_prompt="Moonlit fort gate")
    provider.fetch_for_scene(scene, tmp_path, aspect_ratio="9:16")
    assert seen["aspect_ratio"] == "9:16"
