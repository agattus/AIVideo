"""Tests for generative asset acquisition (Gemini image + Pollinations)."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import unquote

import pytest
from PIL import Image

from youtube_pipeline.assets.provider import STYLE_PROMPT_SUFFIX, AssetService
from youtube_pipeline.models import SceneData, VideoScript


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any] | None = None,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content
        self.text = str(payload)
        self.headers = headers or {"content-type": "image/jpeg"}

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _scene(scene_id: int = 0) -> SceneData:
    return SceneData(
        scene_id=scene_id,
        script_text="Manu boards the ancient wooden ark.",
        visual_prompt=(
            "(Epic cinematic ancient Indian mythology, hyper-detailed, "
            "continuous character design: Manu boards an ancient wooden ark "
            "guided by a golden divine fish, saffron robes, oil-lamp firelight)"
        ),
        keywords=["manu", "wooden ark", "golden fish"],
        duration=3.0,
    )


def _jpeg_bytes(color: tuple[int, int, int] = (40, 80, 120)) -> bytes:
    from io import BytesIO

    buf = BytesIO()
    Image.new("RGB", (320, 180), color).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_style_augmented_prompt_appends_cinematic_suffix() -> None:
    prompt = AssetService._style_augmented_prompt(
        "A lone lighthouse on a cliff",
        "cinematic",
    )
    assert "lone lighthouse" in prompt
    assert "cinematic lighting" in prompt
    assert STYLE_PROMPT_SUFFIX["cinematic"].split(",")[0] in prompt


def test_normalize_image_bytes_decodes_base64_jpeg() -> None:
    jpeg = _jpeg_bytes((10, 20, 30))
    encoded = base64.b64encode(jpeg)
    assert AssetService._normalize_image_bytes(encoded) == jpeg
    assert AssetService._normalize_image_bytes(encoded.decode("ascii")) == jpeg
    assert AssetService._normalize_image_bytes(jpeg) == jpeg


def test_looks_blank_image_detects_black(tmp_path: Path) -> None:
    black = tmp_path / "black.jpg"
    Image.new("RGB", (64, 64), (0, 0, 0)).save(black, format="JPEG")
    colorful = tmp_path / "color.jpg"
    Image.new("RGB", (64, 64), (180, 40, 90)).save(colorful, format="JPEG")
    assert AssetService._looks_blank_image(black) is True
    assert AssetService._looks_blank_image(colorful) is False


def test_imagen_generates_and_saves_jpg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import AssetProvider, Settings

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        asset_provider=AssetProvider.IMAGEN,
        gemini_api_key="test-gemini-key",
        imagen_model="gemini-2.5-flash-image",
    )
    service = AssetService(settings)
    jpeg = _jpeg_bytes((12, 90, 160))
    captured: dict[str, Any] = {}

    def fake_generate(prompt: str, *, model: str) -> bytes:
        captured["prompt"] = prompt
        captured["model"] = model
        return jpeg

    monkeypatch.setattr(service, "_generate_imagen", fake_generate)

    asset = service.fetch_for_scene(_scene(0), tmp_path, style="cinematic")
    assert asset.source == "imagen"
    assert asset.media_type == "image"
    assert Path(asset.path).name == "scene_00.jpg"
    assert Path(asset.path).exists()
    assert Path(asset.path).stat().st_size > 100
    assert captured["model"] == "gemini-2.5-flash-image"
    assert "continuous character design" in captured["prompt"]
    assert "cinematic lighting" in captured["prompt"]


def test_generate_gemini_image_uses_generate_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import AssetProvider, Settings

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        asset_provider=AssetProvider.IMAGEN,
        gemini_api_key="test-gemini-key",
        imagen_model="gemini-2.5-flash-image",
    )
    service = AssetService(settings)
    jpeg = _jpeg_bytes((20, 40, 60))
    captured: dict[str, Any] = {}

    class _FakeModels:
        def generate_content(self, *, model, contents, config):
            captured["model"] = model
            captured["contents"] = contents
            captured["response_modalities"] = config.response_modalities
            captured["aspect_ratio"] = config.image_config.aspect_ratio
            return SimpleNamespace(
                parts=[
                    SimpleNamespace(
                        inline_data=SimpleNamespace(data=jpeg),
                        as_image=None,
                    )
                ],
                candidates=[],
            )

    class _FakeClient:
        def __init__(self, *, api_key: str):
            captured["api_key"] = api_key
            self.models = _FakeModels()

    import sys

    fake_types = SimpleNamespace(
        GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        ImageConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        GenerateImagesConfig=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    fake_genai_mod = SimpleNamespace(Client=_FakeClient, types=fake_types)
    google_pkg = SimpleNamespace(genai=fake_genai_mod)
    monkeypatch.setitem(sys.modules, "google", google_pkg)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)

    raw = service._generate_imagen("epic ark on stormy seas", model="gemini-2.5-flash-image")
    assert raw == jpeg
    assert captured["api_key"] == "test-gemini-key"
    assert captured["model"] == "gemini-2.5-flash-image"
    assert captured["contents"] == "epic ark on stormy seas"
    assert captured["response_modalities"] == ["IMAGE"]
    assert captured["aspect_ratio"] == "16:9"


def test_generate_legacy_imagen_api_still_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import AssetProvider, Settings

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        asset_provider=AssetProvider.IMAGEN,
        gemini_api_key="test-gemini-key",
    )
    service = AssetService(settings)
    jpeg = _jpeg_bytes((90, 20, 40))
    captured: dict[str, Any] = {}

    class _FakeModels:
        def generate_images(self, *, model, prompt, config):
            captured["model"] = model
            captured["prompt"] = prompt
            return SimpleNamespace(
                generated_images=[
                    SimpleNamespace(
                        rai_filtered_reason=None,
                        image=SimpleNamespace(image_bytes=base64.b64encode(jpeg)),
                    )
                ]
            )

    class _FakeClient:
        def __init__(self, *, api_key: str):
            self.models = _FakeModels()

    import sys

    fake_types = SimpleNamespace(
        GenerateImagesConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        GenerateContentConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        ImageConfig=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    fake_genai_mod = SimpleNamespace(Client=_FakeClient, types=fake_types)
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai_mod))
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)

    raw = service._generate_imagen("stormy seas", model="imagen-4.0-generate-001")
    assert raw == jpeg
    assert captured["model"] == "imagen-4.0-generate-001"


def test_imagen_falls_back_to_pollinations_on_api_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import AssetProvider, Settings

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        asset_provider=AssetProvider.IMAGEN,
        gemini_api_key="test-gemini-key",
    )
    service = AssetService(settings)
    jpeg = _jpeg_bytes((30, 140, 90))

    def boom(*args, **kwargs):
        raise RuntimeError("gemini image unavailable")

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None, headers=None):
            return _FakeResponse(200, content=jpeg)

    monkeypatch.setattr(service, "_generate_imagen", boom)
    monkeypatch.setattr("youtube_pipeline.assets.provider.httpx.Client", _Client)

    asset = service.fetch_for_scene(_scene(2), tmp_path, style="cinematic")
    assert asset.source == "pollinations"
    assert Path(asset.path).name == "scene_02.jpg"
    assert not AssetService._looks_blank_image(Path(asset.path))


def test_pollinations_encodes_visual_prompt_and_saves_jpg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import AssetProvider, Settings

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        asset_provider=AssetProvider.POLLINATIONS,
    )
    service = AssetService(settings)
    jpeg = _jpeg_bytes()
    captured: dict[str, str] = {}

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None, headers=None):
            captured["url"] = str(url)
            return _FakeResponse(200, content=jpeg)

    monkeypatch.setattr("youtube_pipeline.assets.provider.httpx.Client", _Client)

    asset = service.fetch_for_scene(_scene(0), tmp_path, style="cinematic")
    assert asset.source == "pollinations"
    assert asset.media_type == "image"
    assert Path(asset.path).name == "scene_00.jpg"
    assert Path(asset.path).exists()
    assert Path(asset.path).stat().st_size > 100

    assert "image.pollinations.ai/prompt/" in captured["url"]
    assert "width=1920" in captured["url"]
    assert "height=1080" in captured["url"]
    assert "nologo=true" in captured["url"]
    decoded = unquote(captured["url"])
    assert "continuous character design" in decoded
    assert "ancient wooden ark" in decoded


def test_pollinations_fallback_on_http_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import AssetProvider, Settings

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        asset_provider=AssetProvider.POLLINATIONS,
    )
    service = AssetService(settings)

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None, headers=None):
            raise RuntimeError("network down")

    monkeypatch.setattr("youtube_pipeline.assets.provider.httpx.Client", _Client)

    asset = service.fetch_for_scene(_scene(1), tmp_path, style="cinematic")
    assert asset.source == "black_fallback"
    assert Path(asset.path).name == "scene_01.jpg"


def test_acquire_all_writes_sequential_jpg_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import AssetProvider, Settings

    settings = Settings(
        output_dir=tmp_path / "out",
        assets_cache_dir=tmp_path / "cache",
        asset_provider=AssetProvider.POLLINATIONS,
    )
    service = AssetService(settings)

    script = VideoScript(
        title="Matsya",
        full_script="One. Two.",
        style="cinematic",
        scenes=[_scene(0), _scene(1).model_copy(update={"scene_id": 1, "script_text": "Two."})],
    )

    def fake_fetch(scene, output_dir, *, style="cinematic"):
        from youtube_pipeline.models import MediaAsset

        path = Path(output_dir) / f"scene_{scene.scene_id:02d}.jpg"
        path.write_bytes(_jpeg_bytes())
        return MediaAsset(
            scene_id=scene.scene_id,
            path=str(path),
            source="pollinations",
            media_type="image",
        )

    monkeypatch.setattr(service, "fetch_for_scene", fake_fetch)
    assets = service.acquire_all(script, tmp_path / "assets")
    names = sorted(Path(a.path).name for a in assets)
    assert names == ["scene_00.jpg", "scene_01.jpg"]
    assert all(a.source == "pollinations" for a in assets)
