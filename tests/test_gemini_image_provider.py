from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from youtube_pipeline.exceptions import AssetAcquisitionError, ConfigurationError
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


def test_fetch_for_scene_requests_image_modality(tmp_path: Path):
    """_generate should ask the API for IMAGE output, not just TEXT."""
    from youtube_pipeline.assets.gemini_image import GeminiImageProvider

    settings = Settings(
        _env_file=None,
        gemini_api_key="test-key",
        gemini_image_model="gemini-2.5-flash-image",
        asset_provider="gemini_image",
    )
    provider = GeminiImageProvider(settings)
    scene = SceneData(scene_id=0, script_text="Hello", visual_prompt="A red apple")

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
        provider.fetch_for_scene(scene, tmp_path)

    _, kwargs = model.generate_content.call_args
    generation_config = kwargs.get("generation_config") or {}
    assert "IMAGE" in generation_config.get("response_modalities", [])


def test_text_only_response_raises_asset_acquisition_error(tmp_path: Path):
    """A response with only text parts (no inline_data) must fail, not silently pass."""
    from youtube_pipeline.assets.gemini_image import GeminiImageProvider

    settings = Settings(
        _env_file=None,
        gemini_api_key="test-key",
        gemini_image_model="gemini-2.5-flash-image",
        asset_provider="gemini_image",
    )
    provider = GeminiImageProvider(settings)
    scene = SceneData(scene_id=0, script_text="Hello", visual_prompt="A red apple")

    text_part = MagicMock()
    text_part.inline_data = None
    text_part.text = "I can't generate that image."
    response = MagicMock()
    response.parts = [text_part]
    response.candidates = [MagicMock()]

    with patch("youtube_pipeline.assets.gemini_image.genai") as genai:
        model = MagicMock()
        model.generate_content.return_value = response
        genai.GenerativeModel.return_value = model
        with pytest.raises(AssetAcquisitionError):
            provider.fetch_for_scene(scene, tmp_path)

    # Deterministic "no image data" failures must not be retried 3x.
    assert model.generate_content.call_count == 1


def test_transient_error_is_retried(tmp_path: Path):
    """Network/transport-style errors (not AssetAcquisitionError) may still retry."""
    from youtube_pipeline.assets.gemini_image import GeminiImageProvider

    settings = Settings(
        _env_file=None,
        gemini_api_key="test-key",
        gemini_image_model="gemini-2.5-flash-image",
        asset_provider="gemini_image",
    )
    provider = GeminiImageProvider(settings)
    scene = SceneData(scene_id=0, script_text="Hello", visual_prompt="A red apple")

    with patch("youtube_pipeline.assets.gemini_image.genai") as genai:
        model = MagicMock()
        model.generate_content.side_effect = TimeoutError("deadline exceeded")
        genai.GenerativeModel.return_value = model
        with pytest.raises(AssetAcquisitionError):
            provider.fetch_for_scene(scene, tmp_path)

    assert model.generate_content.call_count == 3


def test_factory_builds_gemini_image():
    from youtube_pipeline.assets.factory import build_asset_provider

    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        asset_provider="gemini_image",
    )
    provider = build_asset_provider(settings)
    assert provider.name == "gemini_image"
