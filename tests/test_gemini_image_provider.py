from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from youtube_pipeline.exceptions import ConfigurationError
from youtube_pipeline.models import SceneData


def _tiny_png_bytes() -> bytes:
    # 1x1 PNG
    import base64
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


def test_fetch_for_scene_writes_image(tmp_path: Path):
    from youtube_pipeline.assets.gemini_image import GeminiImageProvider

    settings = Settings(
        _env_file=None,
        gemini_api_key="test-key",
        gemini_image_model="gemini-2.5-flash-image",
        asset_provider="gemini_image",
    )
    provider = GeminiImageProvider(settings)
    scene = SceneData(
        scene_id=0,
        script_text="Hello",
        visual_prompt="Cinematic mountain at dawn",
    )

    part = MagicMock()
    part.inline_data = MagicMock()
    part.inline_data.mime_type = "image/png"
    part.inline_data.data = _tiny_png_bytes()
    response = MagicMock()
    response.parts = [part]
    response.candidates = [MagicMock()]

    with patch("youtube_pipeline.assets.gemini_image.genai") as genai:
        model = MagicMock()
        model.generate_content.return_value = response
        genai.GenerativeModel.return_value = model
        asset = provider.fetch_for_scene(scene, tmp_path)

    assert asset.scene_id == 0
    assert asset.source == "gemini_image"
    assert asset.media_type == "image"
    assert Path(asset.path).exists()
    assert Path(asset.path).stat().st_size > 10


def test_missing_api_key_raises():
    from youtube_pipeline.assets.gemini_image import GeminiImageProvider

    settings = Settings(_env_file=None, gemini_api_key=None, asset_provider="gemini_image")
    with pytest.raises(ConfigurationError):
        GeminiImageProvider(settings)


def test_factory_builds_gemini_image():
    from youtube_pipeline.assets.factory import build_asset_provider

    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        asset_provider="gemini_image",
    )
    provider = build_asset_provider(settings)
    assert provider.name == "gemini_image"
