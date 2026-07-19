from __future__ import annotations

from pathlib import Path

import pytest

from youtube_pipeline.assets.provider import AssetService
from youtube_pipeline.exceptions import AssetAcquisitionError, ConfigurationError
from youtube_pipeline.models import SceneData


def _scene(scene_id: int = 0) -> SceneData:
    return SceneData(
        scene_id=scene_id,
        script_text="Black holes bend light.",
        visual_prompt="Warped spacetime around a dark sphere",
        keywords=["black hole", "space", "gravity"],
        duration=3.0,
    )


def test_pixabay_provider_requires_key(tmp_path: Path) -> None:
    from config.settings import AssetProvider, Settings

    settings = Settings(
        asset_provider=AssetProvider.PIXABAY,
        pixabay_api_key=None,
        openai_api_key="sk_should_not_be_used",
        pexels_api_key="pexels_should_not_be_used",
    )
    with pytest.raises(ConfigurationError, match="PIXABAY_API_KEY"):
        AssetService(settings)


def test_pixabay_chain_skips_pexels_and_openai(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import AssetProvider, Settings

    settings = Settings(
        asset_provider=AssetProvider.PIXABAY,
        pixabay_api_key="pixabay-test",
        openai_api_key="sk_should_not_be_used",
        pexels_api_key="pexels_should_not_be_used",
    )
    service = AssetService(settings)

    calls: list[str] = []

    def boom_pexels(*args, **kwargs):
        calls.append("pexels")
        raise AssertionError("Pexels must not be called when ASSET_PROVIDER=pixabay")

    def boom_openai(*args, **kwargs):
        calls.append("openai")
        raise AssertionError("OpenAI must not be called when ASSET_PROVIDER=pixabay")

    monkeypatch.setattr(service, "_fetch_pexels_video", boom_pexels)
    monkeypatch.setattr(service, "_fetch_pexels_image", boom_pexels)
    monkeypatch.setattr(service, "_fetch_openai_image", boom_openai)

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None, headers=None):
            calls.append(str(url))
            if "api/videos" in str(url):
                return _Resp(
                    200,
                    {
                        "hits": [
                            {
                                "duration": 6,
                                "user": "Ada",
                                "videos": {
                                    "medium": {
                                        "url": "https://example.com/clip.mp4",
                                        "width": 1280,
                                        "height": 720,
                                    }
                                },
                            }
                        ]
                    },
                )
            if str(url).endswith(".mp4"):
                return _Resp(200, content=b"fake-mp4")
            return _Resp(404, {})

    class _Resp:
        def __init__(self, status_code, payload=None, content=b""):
            self.status_code = status_code
            self._payload = payload or {}
            self.content = content
            self.text = str(payload)

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    monkeypatch.setattr("youtube_pipeline.assets.provider.httpx.Client", _Client)

    asset = service.fetch_for_scene(_scene(0), tmp_path, style="cinematic")
    assert asset.source == "pixabay_video"
    assert Path(asset.path).name == "scene_00.mp4"
    assert "pexels" not in calls
    assert "openai" not in calls
    assert any("pixabay.com/api/videos" in c for c in calls)


def test_pixabay_falls_back_to_images_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import AssetProvider, Settings

    settings = Settings(
        asset_provider=AssetProvider.PIXABAY,
        pixabay_api_key="pixabay-test",
    )
    service = AssetService(settings)

    openai_called = {"value": False}

    def boom_openai(*args, **kwargs):
        openai_called["value"] = True
        raise AssertionError("OpenAI must not be called")

    monkeypatch.setattr(service, "_fetch_openai_image", boom_openai)

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None, headers=None):
            url = str(url)
            if "api/videos" in url:
                return _Resp(200, {"hits": []})
            if url.rstrip("/").endswith("/api") or url.endswith("/api/"):
                return _Resp(
                    200,
                    {
                        "hits": [
                            {
                                "largeImageURL": "https://example.com/photo.jpg",
                                "imageWidth": 1920,
                                "imageHeight": 1080,
                                "user": "Bob",
                            }
                        ]
                    },
                )
            if url.endswith(".jpg"):
                return _Resp(200, content=b"fake-jpg")
            return _Resp(404, {})

    class _Resp:
        def __init__(self, status_code, payload=None, content=b""):
            self.status_code = status_code
            self._payload = payload or {}
            self.content = content
            self.text = str(payload)

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    monkeypatch.setattr("youtube_pipeline.assets.provider.httpx.Client", _Client)

    asset = service.fetch_for_scene(_scene(2), tmp_path, style="cinematic")
    assert asset.source == "pixabay_image"
    assert Path(asset.path).name == "scene_02.jpg"
    assert openai_called["value"] is False


def test_pixabay_exhausted_does_not_call_openai(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import AssetProvider, Settings

    settings = Settings(
        asset_provider=AssetProvider.PIXABAY,
        pixabay_api_key="pixabay-test",
        openai_api_key="sk_unused",
    )
    service = AssetService(settings)
    monkeypatch.setattr(service, "_fetch_pixabay_video", lambda *a, **k: None)
    monkeypatch.setattr(service, "_fetch_pixabay_image", lambda *a, **k: None)

    def boom_openai(*args, **kwargs):
        raise AssertionError("OpenAI must not be called")

    monkeypatch.setattr(service, "_fetch_openai_image", boom_openai)

    with pytest.raises(AssetAcquisitionError, match="Pixabay-only"):
        service.fetch_for_scene(_scene(0), tmp_path, style="cinematic")
